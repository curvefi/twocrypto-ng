# pragma version 0.4.3
# pragma optimize gas

"""
@title YB Oraclized Policy

@notice Twocrypto policy for a YieldBasis market: swap fees priced off Pyth
        Lazer reports at the market's crvUSD rate, a trend-gated dual-EMA
        price_scale target, and an LT deposit ratio check.
Notable features are:
    - A swap toward the report pays base_fee plus a share of its edge; every
      other operation pays fallback_fee
    - Optionally, coin1's price is the Pyth feed's times, or divided by, a
      Curve pool's price_oracle basis, say WBTC/USD from BTC/USD and WBTC in
      cbBTC
    - get_target(), get_report(), get_fee_with_report() and
      get_dy_with_report() share the pool hooks' code: at the same pool state
      and time, a report in the bank gets what they show

@dev Port of the backtested `report_lean` policy (curve-fx-sim twocrypto-cpp,
     policies/report_lean.hpp) plus yb-core's LTAdmissionPolicy gate. This
     contract holds the pricing rules and the order of operations; three
     modules in ./modules hold the rest:
         pyth_reports      coin1's USD report from a PythReportBank: feed,
                           Curve pool basis and price bounds
         policy_math       the pool math's get_p, the pool's swap for
                           get_dy_with_report, and the EMA
         yb_lt_gate        the LT deposit ratio check

     FEE
     A swap whose marginal price moves toward the reported price without
     passing it pays base_fee plus `capture` of its edge at the report above
     base_fee, at most fallback_fee. The discount fades into fallback_fee with
     the square root of the report's age and is gone at relax_time.

     CRVUSD RATE
     Fees value the report in coin0 at the rate the market's LT reads: the
     stablecoin aggregator behind the LevAMM's price oracle, as LT.set_amm
     finds it, immutable in both. Its stored last_price() counts while at most
     RATE_MAX_AGE old, else price(), the rate its price_w() would store. A rate
     outside [MIN_RATE, MAX_RATE] prices no discount.

     DRIVER
     A fast and a slow EMA of an observed price, both with true half-lives. The
     target follows the observation as far as the two EMAs disagree, and each
     touch requests half the gap from price_scale to it, at most step_cap of
     price_scale.

     CALLERS
         pool              get_fee, get_price_scale, update_pool_state
         anyone            sync, views; reports are delivered to the bank
         owner (YB DAO)    set_policy_config, set_price_bounds, set_ratio_tolerance,
                           set_killed, ownership
         emergency admin   set_killed

     UNITS
     Fees in FEE_PRECISION (1e10 = 100%). Prices and EMAs have 18 decimals: a
     report prices coin1 in USD (1e18 = $1). Fees value it in coin0 at the
     crvUSD rate; the driver counts coin0 as one USD. Pyth times are
     microseconds. A hook that returns 0 hands the pool its native fee or
     price_scale target.

     A RAMPS
     A is cached at deployment and by sync(). During a ramp a swap re-solves D
     before asking for the fee and pays fallback_fee; get_dy_with_report solves
     the same D and quotes it too. Call sync() once the pool has checkpointed
     its final A.

@license Copyright (c) Curve.Fi, 2026 - all rights reserved

@author curve.fi
"""

################################################################
#                            MODULES                           #
################################################################

from snekmate.auth import ownable
from .modules import policy_math as math  # snekmate also has a math module
from .modules import pyth_reports
from .modules import yb_lt_gate as lt_gate

initializes: ownable
initializes: lt_gate
initializes: math
initializes: pyth_reports
exports: (
    ownable.owner,
    ownable.transfer_ownership,
    ownable.renounce_ownership,
    pyth_reports.BANK,
    pyth_reports.FEED_ID,
    pyth_reports.CHANNEL,
    pyth_reports.BASIS_POOL,
    pyth_reports.INVERT_BASIS,
    pyth_reports.price_bounds,
    lt_gate.AMM,
    lt_gate.ratio_tolerance,
    lt_gate.cached_supply,
    lt_gate.amm_surplus,
)

################################################################
#                           CONSTANTS                          #
################################################################

N_COINS: constant(uint256) = 2
PRECISION: constant(uint256) = 10**18
FEE_PRECISION: constant(uint256) = 10**10  # Twocrypto fee units: 10**10 = 100%
MIN_FEE: constant(uint256) = 10**5  # Twocrypto MIN_FEE (0.1 bp): lower fees get clamped
# The pool steps price_scale one fifth of the way to the target (tweak_price)
TWEAK_PRICE_MULTIPLIER: constant(uint256) = 5

RATE_MAX_AGE: constant(uint256) = 14_400  # 4 hours
MIN_RATE: constant(uint256) = PRECISION // 2  # $0.50
MAX_RATE: constant(uint256) = 2 * PRECISION  # $2

################################################################
#                          INTERFACES                          #
################################################################

interface Pool:
    def A() -> uint256: view
    def D() -> uint256: view
    def coins(i: uint256) -> address: view
    def price_scale() -> uint256: view  # nonreentrant: reverts inside a pool operation


interface LevAMM:
    def PRICE_ORACLE_CONTRACT() -> address: view


interface LPOracle:
    def AGG() -> address: view


interface StableAggregator:
    def price() -> uint256: view
    def last_price() -> uint256: view
    def last_timestamp() -> uint256: view

################################################################
#                            STRUCTS                           #
################################################################

struct FeeConfig:
    base_fee: uint256  # FEE_PRECISION: floor of a discounted fee
    capture: uint256  # PRECISION: share of the reported edge above base_fee
    fallback_fee: uint256  # FEE_PRECISION: fee without a discount, and the cap
    relax_time: uint256  # seconds: report age at which the discount is gone


struct DriverConfig:
    fast_half_life: uint256  # seconds
    slow_half_life: uint256  # seconds
    trend_gate: uint256  # WAD: |fast / slow - 1| at which the target is the observed price
    step_cap: uint256  # WAD: largest requested price_scale move per touch
    report_lifetime: uint256  # seconds: report age below which the EMAs observe it; 0 never


struct PolicyConfig:
    fee: FeeConfig
    driver: DriverConfig


# Pool geometry as of the last callback or sync(); EMAs and spot as of the last
# callback. get_fee compares an operation's balances with it.
struct State:
    last_update_ts: uint256  # block.timestamp of the last callback
    fast_ema: uint256
    slow_ema: uint256
    price_scale: uint256
    xp: uint256[N_COINS]  # balances, coin1 scaled by price_scale
    D: uint256
    last_prices: uint256  # the pool's spot after the last callback's operation

################################################################
#                            EVENTS                            #
################################################################

event SetPolicyConfig:
    config: PolicyConfig


event SetKilled:
    is_killed: bool

################################################################
#                            STORAGE                           #
################################################################

POOL: public(immutable(address))
EMERGENCY_ADMIN: public(immutable(address))
AGGREGATOR: public(immutable(address))  # crvUSD in USD: the stablecoin aggregator LT reads

config: public(PolicyConfig)
is_killed: public(bool)
state: public(State)  # state.xp[0] is the LT gate's stablecoin baseline
cached_A: public(uint256)  # the pool's A as of deployment or the last sync()

################################################################
#                         CONSTRUCTOR                          #
################################################################

@deploy
def __init__(
    pool: address,
    amm: address,
    bank: address,
    feed_id: uint32,
    channel: uint8,
    basis_pool: address,
    invert_basis: bool,
    emergency_admin: address,
    bounds: pyth_reports.PriceBounds,
    config: PolicyConfig,
    ratio_tolerance: uint256,
):
    """
    @notice The deployer becomes the owner
    @param pool Twocrypto pool; coin0 is the LevAMM's stablecoin
    @param amm LevAMM that holds the pool's LP as collateral
    @param bank PythReportBank that stores the reports
    @param feed_id Pyth Lazer feed of coin1/USD, or of the asset it wraps
    @param channel Pyth Lazer channel of the reports this policy reads
    @param basis_pool Curve stableswap-ng pool whose price_oracle(0) prices
           coin1 in the feed's asset, or its inverse; 0 for none
    @param invert_basis True when price_oracle(0) prices the feed's asset in coin1
    @param emergency_admin May kill and revive the policy, as may the owner
    @param bounds Initial price bounds
    @param config Initial policy config
    @param ratio_tolerance Initial LT gate tolerance, WAD
    """
    assert pool != empty(address), "pool=0"
    assert emergency_admin != empty(address), "emergency admin=0"

    # Checks the market: one pool and LevAMM, coin0 unscaled, no admin fee
    lt_gate.__init__(pool, amm, ratio_tolerance)
    math.__init__(pool)
    pyth_reports.__init__(
        bank, feed_id, channel, basis_pool, invert_basis, staticcall Pool(pool).coins(1), bounds
    )
    aggregator: address = staticcall LPOracle(staticcall LevAMM(amm).PRICE_ORACLE_CONTRACT()).AGG()
    rate: uint256 = staticcall StableAggregator(aggregator).price()  # reverts unless it is one
    ownable.__init__()

    POOL = pool
    EMERGENCY_ADMIN = emergency_admin
    AGGREGATOR = aggregator
    self.cached_A = staticcall Pool(pool).A()
    self._set_policy_config(config)

################################################################
#                          POOL HOOKS                          #
################################################################

@external
@view
def get_fee(xp: uint256[N_COINS]) -> uint256:
    """
    @notice Fee of the pool operation in progress: a swap is priced against the
            bank's report (see _get_fee), anything else pays fallback_fee
    @param xp Pool balances after the operation and before its fee, coin1 scaled
           by price_scale
    @return FEE_PRECISION fee, or 0 for the pool's native fee while killed
    """
    if self.is_killed:
        return 0
    old_xp: uint256[N_COINS] = self.state.xp
    # Only a swap can earn a discount: anything else skips the bank
    if not self._is_swap(xp, old_xp):
        return self.config.fee.fallback_fee
    relax_time_us: uint256 = self.config.fee.relax_time * 1_000_000
    report: pyth_reports.Report = pyth_reports._stored_report(relax_time_us)
    return self._get_fee(xp, old_xp, 0, report.asset_price, report.age_us)


@external
@view
def get_price_scale() -> uint256:
    """
    @notice Twocrypto's price_scale target, or 0 for the native target before
            attachment or while killed
    @dev The pool steps a fifth of the way to it, so this is price_scale plus
         five times half the gap to get_target(), at most step_cap of
         price_scale; config bounds keep the request within 5 * 60 bp = 3%. The
         pool's oracle clamp, step limits and profit gate still apply. The pool
         asks only in its first tweak_price at a new timestamp that passes its
         profit test.
    """
    if self.is_killed:
        return 0
    snapshot: State = self.state
    scale: uint256 = snapshot.price_scale
    if scale == 0:
        return 0
    target: uint256 = self._target(snapshot)
    move: uint256 = min(
        (max(target, scale) - min(target, scale)) // 2,
        scale * self.config.driver.step_cap // PRECISION,
    )
    if target >= scale:
        return scale + TWEAK_PRICE_MULTIPLIER * move
    return scale - TWEAK_PRICE_MULTIPLIER * move


@external
def update_pool_state(
    xp: uint256[N_COINS],
    price_scale: uint256,
    price_oracle: uint256,
    last_prices: uint256,
    _virtual_price: uint256,
    _xcp_profit: uint256,
    D: uint256,
    _oracle_timestamp: uint256,
):
    """
    @notice Pool callback after every operation, with its post-operation state:
            gate LT deposits, settle the EMAs and store the snapshot, whose spot
            the next touch observes
    @dev A balanced removal calls back best-effort with 300k gas: if this fails,
         the pool carries on with a stale snapshot when it had at least 500k gas
         before the call, and reverts otherwise. Until sync(), the LT gate can
         then miss one deposit (see yb_lt_gate).
    """
    assert msg.sender == POOL, "auth!"

    snapshot: State = self.state
    # Gate first, against the previous snapshot: a revert unwinds an LT deposit
    if not self.is_killed:
        lt_gate._update(xp[0], snapshot.xp[0])

    # The attachment callback seeds both EMAs with the pool's price_oracle
    fast: uint256 = price_oracle
    slow: uint256 = price_oracle
    if snapshot.price_scale != 0:
        fast = snapshot.fast_ema
        slow = snapshot.slow_ema
        # Later touches of a block keep the EMAs and skip the observation
        if block.timestamp != snapshot.last_update_ts:
            fast, slow = self._project_emas(snapshot, self._observation(snapshot))

    self.state = State(
        last_update_ts=block.timestamp,
        fast_ema=fast,
        slow_ema=slow,
        price_scale=price_scale,
        xp=xp,
        D=D,
        last_prices=last_prices,
    )

################################################################
#                   PERMISSIONLESS FUNCTIONS                   #
################################################################

@external
def sync():
    """
    @notice Re-read the pool's A, the fee snapshot's geometry and the LT gate's
            baselines; the EMAs wait for the next callback. Anyone may call:
            after a ramp's final pool checkpoint, a failed balanced-removal
            callback, or an LP gift to the LevAMM.
    """
    self._sync()

################################################################
#                         VIEW FUNCTIONS                       #
################################################################

@external
@view
def get_target() -> uint256:
    """
    @notice Where the driver steers price_scale: the trend-gated target in USD
            per coin1 (crvUSD at $1), before get_price_scale's capped half-gap
            step; 0 while killed or before attachment
    """
    if self.is_killed:
        return 0
    snapshot: State = self.state
    if snapshot.price_scale == 0:
        return 0
    return self._target(snapshot)


@external
@view
def get_emas() -> uint256[2]:
    """
    @notice [fast EMA, slow EMA] of the driver projected to now, in USD per coin1;
            [0, 0] before attachment
    """
    snapshot: State = self.state
    if snapshot.price_scale == 0:
        return [0, 0]
    if block.timestamp == snapshot.last_update_ts:  # as the callback settles them
        return [snapshot.fast_ema, snapshot.slow_ema]
    fast: uint256 = 0
    slow: uint256 = 0
    fast, slow = self._project_emas(snapshot, self._observation(snapshot))
    return [fast, slow]


@external
@view
def get_report() -> (uint256, uint256, uint256):
    """
    @notice The bank's newest report as the policy prices it, at any age
    @return (coin1 in USD with this block's basis, coin1 in coin0 at this
            block's crvUSD rate, the feed's observation time in us). Prices are
            0 when the report is absent or the policy killed; the coin0 price
            also when the rate is out of bounds. Fees use it younger than
            relax_time, the driver younger than report_lifetime.
    """
    if self.is_killed:
        return 0, 0, 0
    report: pyth_reports.Report = pyth_reports._stored_report(max_value(uint256))
    if report.asset_price == 0:
        return 0, 0, report.observation_us
    return (
        report.asset_price,
        self._coin0_price(report.asset_price),
        report.observation_us,
    )


@external
@view
def get_fee_with_report(
    xp: uint256[N_COINS], feed_price: uint256, report_age_us: uint256
) -> uint256:
    """
    @notice get_fee(xp) with a hypothetical report of this Pyth feed price in
            USD (1e18 = $1, before the basis) observed report_age_us
            microseconds ago; pass age 0 for an observation after the block.
            This block's basis, price bounds and crvUSD rate apply, as to a
            report in the bank. Nothing checks a signature or the bank's
            delivery window.
    """
    return self._fee_with_report(xp, 0, feed_price, report_age_us)


@external
@view
def get_dy_with_report(
    i: uint256, j: uint256, dx: uint256, feed_price: uint256, report_age_us: uint256
) -> uint256:
    """
    @notice pool.get_dy(i, j, dx) with a hypothetical report of this Pyth feed
            price in USD (1e18 = $1, before the basis) observed report_age_us
            microseconds ago; pass age 0 for an observation after the block.
            This block's basis, price bounds and crvUSD rate apply, as to a
            report in the bank. Nothing checks a signature or the bank's
            delivery window.
    """
    dy: uint256 = 0
    xp: uint256[N_COINS] = empty(uint256[N_COINS])
    D: uint256 = 0
    dy, xp, D = math._get_dy_nofee(i, j, dx)
    return math._apply_fee(dy, xp, self._fee_with_report(xp, D, feed_price, report_age_us))

################################################################
#                        OWNER FUNCTIONS                       #
################################################################

@external
def set_policy_config(config: PolicyConfig):
    """
    @notice Replace the whole policy config. Owner only.
    @dev No EMA checkpoint: new half-lives apply to the whole interval since the
         last touch, and raising relax_time or report_lifetime can revive a
         bank report.
    """
    ownable._check_owner()
    self._set_policy_config(config)


@external
def set_price_bounds(bounds: pyth_reports.PriceBounds):
    """
    @notice Set the sanity bounds on coin1's USD price. Owner only.
    @dev Bounds apply at every use of a report, the bank's current record
         included.
    """
    ownable._check_owner()
    pyth_reports._set_price_bounds(bounds)


@external
def set_ratio_tolerance(ratio_tolerance: uint256):
    """@notice Set the LT gate's tolerance, WAD, at most 10 bp. Owner only."""
    ownable._check_owner()
    lt_gate._set_ratio_tolerance(ratio_tolerance)


@external
def set_killed(is_killed: bool):
    """
    @notice Kill (True) or revive the policy. Owner or emergency admin.
    @dev While killed, get_fee and get_price_scale return 0 (the pool's native
         fee and target), the bank, basis pool and aggregator are not read, and
         the LT gate is off, external reads included. Callbacks still settle the
         EMAs, on the pool's spot. Neither killing nor reviving touches reports
         or calls the bank. Reviving calls sync() for the LT gate's baselines,
         so a bank report still young enough counts again at once.
    """
    assert msg.sender == EMERGENCY_ADMIN or msg.sender == ownable.owner, "access"
    if not is_killed:
        self._sync()
    self.is_killed = is_killed
    log SetKilled(is_killed=is_killed)

################################################################
#                      INTERNAL FUNCTIONS                      #
################################################################

# ---------------------------- Fee ----------------------------

@internal
@view
def _get_fee(
    xp: uint256[N_COINS],
    old_xp: uint256[N_COINS],
    quote_D: uint256,
    asset_price: uint256,
    report_age_us: uint256,
) -> uint256:
    """
    @dev The fee of a swap from the snapshot's balances old_xp to xp (see
         _is_swap) against a report of asset_price in USD report_age_us old,
         valued in coin0 at this block's crvUSD rate. Callers pass price 0 for
         no report, including one relax_time old or older.
    @param quote_D The swap's D: 0 for the pool's stored one (the hook), a
           quote's own otherwise
    """
    fallback_fee: uint256 = self.config.fee.fallback_fee
    if asset_price == 0:
        return fallback_fee
    # The swap's D must be the snapshot's. It is not before attachment, after a
    # failed best-effort removal callback, and usually in a swap during an A
    # ramp, which re-solves D first; a quote passes the D it solved.
    D: uint256 = self.state.D
    execution_D: uint256 = quote_D
    if execution_D == 0:
        execution_D = staticcall Pool(POOL).D()
    if D == 0 or execution_D != D:
        return fallback_fee
    report_price: uint256 = self._coin0_price(asset_price)
    if report_price == 0:
        return fallback_fee

    price_scale: uint256 = self.state.price_scale
    coin_in: uint256 = 0 if xp[0] > old_xp[0] else 1
    edge: uint256 = self._reported_edge(xp, old_xp, price_scale, report_price, coin_in)
    if edge == 0:
        return fallback_fee
    fee: uint256 = self._reported_fee(self.config.fee, edge, report_age_us)
    if fee < fallback_fee and self._is_corrective(
        xp, old_xp, D, self.cached_A, price_scale, report_price, coin_in
    ):
        return fee
    return fallback_fee


@internal
@pure
def _is_swap(xp: uint256[N_COINS], old_xp: uint256[N_COINS]) -> bool:
    """@dev One balance rose and the other fell: only a swap can earn a discount."""
    return (xp[0] > old_xp[0] and xp[1] < old_xp[1]) or (xp[0] < old_xp[0] and xp[1] > old_xp[1])


@internal
@pure
def _reported_edge(
    xp: uint256[N_COINS],
    old_xp: uint256[N_COINS],
    price_scale: uint256,
    report_price: uint256,
    coin_in: uint256,
) -> uint256:
    """
    @dev The swap's edge at the report, 1 - input value / output value with both
         legs valued in coin0, rounded up in fee units; 0 when the input is worth
         at least the output. A coin1 amount in xp times report_price /
         price_scale is its value at the report.
    """
    coin_out: uint256 = 1 - coin_in
    input_value: uint256 = xp[coin_in] - old_xp[coin_in]
    output_value: uint256 = old_xp[coin_out] - xp[coin_out]

    if coin_in == 1:
        input_value = input_value * report_price // price_scale
    else:
        output_value = output_value * report_price // price_scale
    if input_value >= output_value:
        return 0
    return FEE_PRECISION - input_value * FEE_PRECISION // output_value


@internal
@pure
def _reported_fee(fee: FeeConfig, reported_edge: uint256, report_age_us: uint256) -> uint256:
    """
    @dev (1 - w) * fresh + w * fallback with w = sqrt(age / relax_time), computed
         as fresh + sqrt((fallback - fresh)**2 * age / relax_time). The caller
         keeps report_age_us below relax_time.
    """
    excess_edge: uint256 = reported_edge - min(reported_edge, fee.base_fee)
    fresh_fee: uint256 = min(
        fee.fallback_fee, fee.base_fee + fee.capture * excess_edge // PRECISION
    )
    if report_age_us == 0 or fresh_fee == fee.fallback_fee:
        return fresh_fee

    # The floored root plus one fee unit never understates the surcharge, and
    # age < relax_time keeps the fee at most fallback_fee
    relax_time_us: uint256 = fee.relax_time * 1_000_000
    discount: uint256 = fee.fallback_fee - fresh_fee
    return fresh_fee + isqrt(discount * discount * report_age_us // relax_time_us) + 1


@internal
@pure
def _is_corrective(
    xp: uint256[N_COINS],
    old_xp: uint256[N_COINS],
    D: uint256,
    A: uint256,
    price_scale: uint256,
    report_price: uint256,
    coin_in: uint256,
) -> bool:
    """@dev The marginal price moves toward the report and does not pass it."""
    # An emptied balance has no marginal price
    if xp[0] == 0 or xp[1] == 0:
        return False
    A_gamma: uint256[N_COINS] = [A, 0]
    # Marginal prices times price_scale are coin0 per coin1, like report_price
    p_before: uint256 = math._get_p(old_xp, D, A_gamma) * price_scale // PRECISION
    p_after: uint256 = math._get_p(xp, D, A_gamma) * price_scale // PRECISION
    if coin_in == 0:
        return p_before < p_after and p_after <= report_price
    return p_before > p_after and p_after >= report_price


@internal
@view
def _coin0_price(usd_price: uint256) -> uint256:
    """
    @dev usd_price (18 decimals) in crvUSD at this block's rate, rounded down,
         or 0 when that rate is out of bounds
    """
    rate: uint256 = 0
    if block.timestamp <= staticcall StableAggregator(AGGREGATOR).last_timestamp() + RATE_MAX_AGE:
        rate = staticcall StableAggregator(AGGREGATOR).last_price()
    else:
        rate = staticcall StableAggregator(AGGREGATOR).price()
    if rate < MIN_RATE or rate > MAX_RATE:
        return 0
    return usd_price * PRECISION // rate

# --------------------------- Driver --------------------------

@internal
@view
def _target(snapshot: State) -> uint256:
    """
    @dev The trend-gated target of the EMAs projected to now: fast + w *
         (observed - fast) with w = min(1, |fast / slow - 1| / trend_gate), or
         fast when trend_gate is 0. slow > 0: the EMAs are convex mixes of
         bounded positive prices.
    """
    observed: uint256 = self._observation(snapshot)
    fast: uint256 = 0
    slow: uint256 = 0
    fast, slow = self._project_emas(snapshot, observed)
    trend_gate: uint256 = self.config.driver.trend_gate
    if trend_gate == 0:
        return fast
    trend: uint256 = (max(fast, slow) - min(fast, slow)) * PRECISION // slow
    if trend >= trend_gate:
        return observed
    if observed >= fast:
        return fast + (observed - fast) * trend // trend_gate
    return fast - (fast - observed) * trend // trend_gate


@internal
@view
def _project_emas(snapshot: State, observation: uint256) -> (uint256, uint256):
    dt: uint256 = block.timestamp - snapshot.last_update_ts
    if dt == 0:  # later touches of a block keep the EMAs
        return snapshot.fast_ema, snapshot.slow_ema
    return (
        math._ema(snapshot.fast_ema, observation, dt, self.config.driver.fast_half_life),
        math._ema(snapshot.slow_ema, observation, dt, self.config.driver.slow_half_life),
    )


@internal
@view
def _observation(snapshot: State) -> uint256:
    """
    @dev What the EMAs and the target observe, bounded to [price_scale / 2,
         2 * price_scale]: the report while younger than report_lifetime
         (separate from the fee's relax_time) and the policy is live, else the
         pool's spot after the previous callback's operation, as in the pool's
         own EMA, so a touch cannot steer them with its own trade.
    """
    price: uint256 = 0
    if not self.is_killed:
        lifetime_us: uint256 = self.config.driver.report_lifetime * 1_000_000
        price = pyth_reports._stored_report(lifetime_us).asset_price
    if price == 0:
        price = snapshot.last_prices
    return min(max(price, snapshot.price_scale // 2), 2 * snapshot.price_scale)

# -------------------------- Quotes ---------------------------

@internal
@view
def _fee_with_report(
    xp: uint256[N_COINS], quote_D: uint256, feed_price: uint256, report_age_us: uint256
) -> uint256:
    """
    @dev get_fee(xp) for a hypothetical report of feed_price (before the basis)
         report_age_us old: 0 while killed, fallback_fee for a non-swap or a
         report relax_time old or older; only a usable report reads the basis
         pool. quote_D as for _get_fee.
    """
    if self.is_killed:
        return 0
    old_xp: uint256[N_COINS] = self.state.xp
    # As get_fee: against a stale snapshot a quote's swap may not look like one
    if not self._is_swap(xp, old_xp):
        return self.config.fee.fallback_fee
    price: uint256 = 0
    if feed_price != 0 and report_age_us < self.config.fee.relax_time * 1_000_000:
        price = pyth_reports._coin1_price(feed_price)
    return self._get_fee(xp, old_xp, quote_D, price, report_age_us)

# ------------------------ Config, sync -----------------------

@internal
def _set_policy_config(config: PolicyConfig):
    fee: FeeConfig = config.fee
    assert fee.base_fee >= MIN_FEE and fee.base_fee <= fee.fallback_fee, "base fee"
    assert fee.fallback_fee <= FEE_PRECISION // 10, "fallback fee"  # 10%
    assert fee.capture <= PRECISION, "capture"
    assert fee.relax_time > 0 and fee.relax_time <= 3_600, "relax time"  # 1 hour

    driver: DriverConfig = config.driver
    # Half-lives from 10 minutes to a week, fast at most slow
    assert (
        driver.fast_half_life >= 600 and driver.fast_half_life <= driver.slow_half_life
    ), "fast half-life"
    assert driver.slow_half_life <= 604_800, "slow half-life"
    assert driver.trend_gate <= PRECISION // 10, "trend gate"  # 10%
    # Up to 60 bp per touch: a requested gap of at most 3% of price_scale
    assert driver.step_cap > 0 and driver.step_cap <= 60 * PRECISION // 10_000, "step cap"
    assert driver.report_lifetime <= 14_400, "report lifetime"  # 4 hours

    self.config = config
    log SetPolicyConfig(config=config)


@internal
def _sync():
    # price_scale() is nonreentrant: this reverts inside a pool operation
    price_scale: uint256 = staticcall Pool(POOL).price_scale()
    assert price_scale > 0, "pool uninitialized"
    self.cached_A = staticcall Pool(POOL).A()
    # Before attachment, leave the snapshot and the gate's supply for the
    # attachment callback to seed together
    attached: bool = self.state.price_scale != 0
    if attached:
        self.state.xp = math._xp(price_scale)
        self.state.D = staticcall Pool(POOL).D()
        self.state.price_scale = price_scale
    lt_gate._sync(attached)
