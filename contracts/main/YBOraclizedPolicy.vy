# pragma version 0.4.3
# pragma optimize gas
"""
@title YBOraclizedPolicy
@notice Twocrypto policy for a YieldBasis market: swap fees priced off signed
        Pyth Lazer reports, a trend-gated dual-EMA price_scale target, and an
        LT deposit ratio check.
@dev Port of the backtested `report_lean` policy (curve-fx-sim twocrypto-cpp,
     policies/report_lean.hpp) plus yb-core's LTAdmissionPolicy gate.

     CALLERS
         pool              get_fee, get_price_scale, update_pool_state
         anyone            deliver_oracle_report, sync, views
         owner (YB DAO)    set_policy_config, set_oracle_config, set_killed, ownership
         emergency admin   set_killed

     UNITS
     Fees in FEE_PRECISION (1e10 = 100%). Prices and EMAs have 18 decimals: a
     report prices coin1 in USD (1e18 = $1) and coin0 (crvUSD) counts as one
     USD. Relative values are WADs (1e18 = 100%). Pyth times are microseconds.
     A hook that returns 0 hands the pool its native fee or price_scale target.

     A RAMPS
     A is cached at deployment and by sync(). During a ramp, quotes and swaps
     can disagree on the fee (see _get_fee). Kill the policy for the ramp, or
     call sync() once the pool has checkpointed its final A.
"""
from snekmate.auth import ownable
from snekmate.utils import math

initializes: ownable
exports: (ownable.owner, ownable.transfer_ownership, ownable.renounce_ownership)


interface Pool:
    def A() -> uint256: view
    def D() -> uint256: view
    def admin_fee() -> uint256: view
    def balances(i: uint256) -> uint256: view
    def price_scale() -> uint256: view  # Nonreentrant: reverts inside a pool operation.
    def user_supply() -> uint256: view
    def balanceOf(account: address) -> uint256: view
    def coins(i: uint256) -> address: view
    def precisions() -> uint256[N_COINS]: view
    # For get_dy_with_report, as TwocryptoView reads them.
    def POLICY() -> address: view
    def MATH() -> Math: view
    def gamma() -> uint256: view
    def future_A_gamma_time() -> uint256: view
    def last_timestamp() -> uint256: view
    def fee_calc(xp: uint256[N_COINS]) -> uint256: view


interface Math:
    def get_y(
        ANN: uint256, gamma: uint256, x: uint256[N_COINS], D: uint256, i: uint256
    ) -> uint256[2]: view
    def newton_D(
        ANN: uint256, gamma: uint256, x_unsorted: uint256[N_COINS], K0_prev: uint256
    ) -> uint256: view


interface LevAMM:
    def COLLATERAL() -> address: view
    def STABLECOIN() -> address: view
    def collateral_amount() -> uint256: view
    def get_debt() -> uint256: view


interface PythLazer:
    def verification_fee() -> uint256: view
    def verifyUpdate(update: Bytes[112]) -> (Bytes[41], address): payable


N_COINS: constant(uint256) = 2
PRECISION: constant(uint256) = 10**18  # Prices, EMAs, capture and relative WADs.
FEE_PRECISION: constant(uint256) = 10**10  # Twocrypto fee units: 10**10 = 100%.
MIN_FEE: constant(uint256) = 10**5  # Twocrypto MIN_FEE (0.1 bp): lower fees get clamped.
A_MULTIPLIER: constant(uint256) = 10_000
LN2: constant(uint256) = 693_147_180_559_945_309
# The pool steps price_scale one fifth of the way to the target (tweak_price).
TWEAK_PRICE_MULTIPLIER: constant(uint256) = 5

PYTH_PAYLOAD_MAGIC: constant(uint256) = 2479346549  # 0x93c7d375: Pyth Lazer payload format.
# Hard limits for report admission (OracleConfig).
MIN_REPORT_PRICE: constant(uint256) = 10**6  # $1e-12
MAX_REPORT_PRICE: constant(uint256) = 10**30  # $1e12
MAX_PAST_WINDOW_US: constant(uint256) = 12_000_000
MAX_FUTURE_WINDOW_US: constant(uint256) = 6_000_000

POOL: public(immutable(address))
AMM: public(immutable(address))
FEED_ID: public(immutable(uint32))  # Pyth Lazer feed of coin1/USD; numeric ids are stable.
EMERGENCY_ADMIN: public(immutable(address))


# Report admission; only deliver_oracle_report reads it.
struct OracleConfig:
    verifier: address  # Pyth Lazer verifier: it decides which signed prices are authentic.
    channel: uint8  # 1 real_time, 2 fixed_rate@50ms, 3 fixed_rate@200ms, 4 fixed_rate@1000ms
    past_window_us: uint256  # oldest admissible observation, before block.timestamp
    future_window_us: uint256  # newest admissible message, after block.timestamp
    min_price: uint256  # sanity bounds on the coin1 price, 1e18 = $1
    max_price: uint256


struct FeeConfig:
    base_fee: uint256  # FEE_PRECISION: floor of a discounted fee.
    capture: uint256  # PRECISION: share of the reported edge above base_fee.
    fallback_fee: uint256  # FEE_PRECISION: fee without a discount, and the cap.
    relax_time: uint256  # seconds: report age at which the discount is gone.


struct DriverConfig:
    fast_half_life: uint256  # seconds
    slow_half_life: uint256  # seconds
    trend_gate: uint256  # WAD: |fast / slow - 1| at which the target is the observed price.
    step_cap: uint256  # WAD: largest requested price_scale move per touch.
    report_lifetime: uint256  # seconds: report age below which the EMAs observe it; 0 never.


struct PolicyConfig:
    fee: FeeConfig
    driver: DriverConfig
    # WAD tolerance around an LT deposit's proportional debt: it absorbs interest
    # and trades between quoting and inclusion. 0 requires exact equality.
    ratio_tolerance: uint256


struct Report:
    asset_price: uint256  # coin1 in USD, 1e18 = $1. 0 before any report and after a kill.
    observation_us: uint256  # Pyth feed update time; kept on a kill as the replay watermark.


# Pool geometry as of the last callback or sync(), EMAs and spot as of the last
# callback. get_fee compares a quote's balances with it.
struct State:
    last_update_ts: uint256  # block.timestamp of the last callback
    fast_ema: uint256
    slow_ema: uint256
    price_scale: uint256
    xp: uint256[N_COINS]  # balances, coin1 scaled by price_scale
    D: uint256
    last_prices: uint256  # the pool's spot after the last callback's operation


config: public(PolicyConfig)
oracle: public(OracleConfig)
is_killed: public(bool)
report: public(Report)
state: public(State)
cached_A: public(uint256)  # the pool's A as of deployment or the last sync()
# LT gate baselines, besides state.xp[0]:
cached_supply: public(uint256)  # pool.user_supply() as of the last callback; 0 until attached
amm_surplus: public(uint256)  # LP gifted to the LevAMM, as of the last add or sync()


event ReportAccepted:
    asset_price: uint256
    observation_us: uint256
    message_us: uint256


event SetPolicyConfig:
    config: PolicyConfig


event SetOracleConfig:
    oracle: OracleConfig


event SetKilled:
    is_killed: bool


@deploy
def __init__(
    pool: address,
    amm: address,
    feed_id: uint32,
    emergency_admin: address,
    oracle: OracleConfig,
    config: PolicyConfig,
):
    """
    @param pool Twocrypto pool; coin0 is the LevAMM's stablecoin
    @param amm LevAMM that holds the pool's LP as collateral
    @param feed_id Pyth Lazer feed of coin1/USD
    @param emergency_admin May kill and unkill the policy, as may the owner
    @param oracle Initial report admission; the deployer becomes the owner
    @param config Initial policy config
    """
    assert pool != empty(address), "pool=0"
    assert feed_id > 0, "feed id"
    assert emergency_admin != empty(address), "emergency admin=0"

    # One market: the LevAMM's collateral is this pool's LP, and its stablecoin
    # is coin0, which the pool holds unscaled.
    assert staticcall LevAMM(amm).COLLATERAL() == pool, "amm collateral"
    assert staticcall LevAMM(amm).STABLECOIN() == staticcall Pool(pool).coins(0), "amm stablecoin"
    assert (staticcall Pool(pool).precisions())[0] == 1, "pool precision"
    # The LT gate measures deposited debt exactly only without a pool admin fee.
    assert staticcall Pool(pool).admin_fee() == 0, "admin fee"

    POOL = pool
    AMM = amm
    FEED_ID = feed_id
    EMERGENCY_ADMIN = emergency_admin
    self.cached_A = staticcall Pool(pool).A()

    ownable.__init__()
    self._set_oracle_config(oracle)
    self._set_policy_config(config)


# ------------------------------------- Fee -------------------------------------


@external
@view
def get_fee(xp: uint256[N_COINS]) -> uint256:
    """
    @notice Fee of the pool operation in progress, against the stored report.
    @dev A swap whose marginal price moves toward the report without passing it
         pays base_fee plus `capture` of its whole-trade edge above base_fee, at
         most fallback_fee. The discount fades into fallback_fee with the square
         root of the report's age and is gone at relax_time. Every other
         operation pays fallback_fee.
    @param xp Pool balances after the operation and before its fee, coin1 scaled
           by price_scale
    @return FEE_PRECISION fee, or 0 for the pool's native fee while killed
    """
    stored_report: Report = self.report
    return self._get_fee(
        xp, stored_report.asset_price, self._report_age_us(stored_report.observation_us)
    )


@external
@view
def get_fee_with_report(
    xp: uint256[N_COINS], report_price: uint256, report_age_us: uint256
) -> uint256:
    """
    @notice Preview get_fee with an unverified report price and observation age;
            pass age 0 for an observation after block.timestamp.
    """
    return self._get_fee(xp, report_price, report_age_us)


@internal
@view
def _get_fee(
    xp: uint256[N_COINS], report_price: uint256, report_age_us: uint256
) -> uint256:
    if self.is_killed:
        return 0

    params: FeeConfig = self.config.fee
    snapshot: State = self.state
    old_xp: uint256[N_COINS] = snapshot.xp

    # A discount requires one balance to rise and the other to fall: a swap.
    if xp[0] >= old_xp[0] and xp[1] >= old_xp[1]:
        return params.fallback_fee
    if xp[0] <= old_xp[0] and xp[1] <= old_xp[1]:
        return params.fallback_fee
    if report_price == 0 or report_age_us >= params.relax_time * 1_000_000:
        return params.fallback_fee
    # The snapshot must match the pool's stored D. It does not before attachment,
    # after a failed best-effort removal callback, and usually in a swap during an
    # A ramp, which stores a re-solved D first (a get_dy quote solves it locally).
    D: uint256 = snapshot.D
    if D == 0 or staticcall Pool(POOL).D() != D:
        return params.fallback_fee

    coin_in: uint256 = 0 if xp[0] > old_xp[0] else 1
    reported_edge: uint256 = self._reported_edge(
        xp, old_xp, snapshot.price_scale, report_price, coin_in
    )
    if reported_edge == 0:
        return params.fallback_fee

    fee: uint256 = self._reported_fee(params, reported_edge, report_age_us)
    if fee < params.fallback_fee and self._is_corrective_swap(
        xp, old_xp, D, snapshot.price_scale, report_price, coin_in
    ):
        return fee
    return params.fallback_fee


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
    @dev The trade's edge at the report, 1 - input value / output value with both
         legs valued in coin0, rounded up in fee units; 0 when the input is worth
         at least the output. A coin1 delta in xp times report_price / price_scale
         is its value at the report.
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
def _reported_fee(
    params: FeeConfig, reported_edge: uint256, report_age_us: uint256
) -> uint256:
    """
    @dev (1 - w) * fresh + w * fallback with w = sqrt(age / relax_time), computed
         as fresh + sqrt((fallback - fresh)**2 * age / relax_time).
    """
    excess_edge: uint256 = reported_edge - min(reported_edge, params.base_fee)
    fresh_fee: uint256 = min(
        params.fallback_fee, params.base_fee + params.capture * excess_edge // PRECISION
    )
    if report_age_us == 0 or fresh_fee == params.fallback_fee:
        return fresh_fee

    # The floored root plus one fee unit never understates the surcharge, and the
    # caller's age < relax_time keeps the fee at most fallback_fee.
    relax_time_us: uint256 = params.relax_time * 1_000_000
    discount: uint256 = params.fallback_fee - fresh_fee
    return fresh_fee + isqrt(discount * discount * report_age_us // relax_time_us) + 1


@internal
@view
def _is_corrective_swap(
    xp: uint256[N_COINS],
    old_xp: uint256[N_COINS],
    D: uint256,
    price_scale: uint256,
    report_price: uint256,
    coin_in: uint256,
) -> bool:
    """The marginal price moves toward the report and does not pass it."""
    # An emptied balance has no marginal price.
    if xp[0] == 0 or xp[1] == 0:
        return False
    A_gamma: uint256[N_COINS] = [self.cached_A, 0]
    # Marginal prices times price_scale are coin0 per coin1, like report_price.
    p_before: uint256 = self._get_p(old_xp, D, A_gamma) * price_scale // PRECISION
    p_after: uint256 = self._get_p(xp, D, A_gamma) * price_scale // PRECISION
    if coin_in == 0:
        return p_before < p_after and p_after <= report_price
    return p_before > p_after and p_after >= report_price


# Copied line by line from StableswapMath.get_p, the pool's math (external there).
@internal
@pure
def _get_p(
    _xp: uint256[N_COINS], _D: uint256, _A_gamma: uint256[N_COINS]
) -> uint256:
    """
    @notice Calculates dx/dy.
    @dev Output needs to be multiplied with price_scale to get the actual value.
    @param _xp Balances of the pool.
    @param _D Current value of D.
    @param _A_gamma Amplification coefficient and gamma.
    """
    # dx_0 / dx_1 only, however can have any number of coins in pool
    ANN: uint256 = unsafe_mul(_A_gamma[0], N_COINS)
    Dr: uint256 = unsafe_div(_D, N_COINS**N_COINS)

    for i: uint256 in range(N_COINS):
        Dr = Dr * _D // _xp[i]

    xp0_A: uint256 = unsafe_div(ANN * _xp[0], A_MULTIPLIER)

    return 10**18 * (xp0_A + unsafe_div(Dr * _xp[0], _xp[1])) // (xp0_A + Dr)


# --------------------------------- Price scale ---------------------------------


@external
@view
def get_price_scale() -> uint256:
    """
    @notice Twocrypto's price_scale target, or 0 for the native target before
            attachment or while killed.
    @dev The EMAs observe the stored report while younger than report_lifetime,
         else the pool's spot after the previous touch. The target is
         fast + w * (observed - fast) with w = min(1, |fast / slow - 1| / trend_gate),
         or fast when trend_gate is 0. Each touch requests half the gap to it, at
         most step_cap of price_scale; the pool's oracle clamp, step limits and
         profit gate still apply. The pool asks only in its first tweak_price at
         a new timestamp that passes its profit test; update_pool_state settles
         the EMAs on every touch.
    """
    if self.is_killed:
        return 0
    snapshot: State = self.state
    scale: uint256 = snapshot.price_scale
    if scale == 0:
        return 0

    observed_price: uint256 = self._observation(snapshot)
    fast: uint256 = 0
    slow: uint256 = 0
    fast, slow = self._project_emas(snapshot, observed_price)

    target: uint256 = fast
    trend_gate: uint256 = self.config.driver.trend_gate
    if trend_gate != 0:
        # |fast / slow - 1| in WAD; slow > 0 as a convex mix of clamped positive prices.
        trend: uint256 = (fast - slow if fast >= slow else slow - fast) * PRECISION // slow
        if trend >= trend_gate:
            target = observed_price
        elif observed_price >= fast:
            target = fast + (observed_price - fast) * trend // trend_gate
        else:
            target = fast - (fast - observed_price) * trend // trend_gate

    gap: uint256 = target - scale if target >= scale else scale - target
    # Config bounds keep the request within 5 * 60 bp = 3% of price_scale.
    move: uint256 = min(gap // 2, scale * self.config.driver.step_cap // PRECISION)
    if target >= scale:
        return scale + TWEAK_PRICE_MULTIPLIER * move
    else:
        return scale - TWEAK_PRICE_MULTIPLIER * move


@external
@view
def get_emas() -> uint256[2]:
    """@return [fast EMA, slow EMA] projected to now, or [0, 0] before attachment."""
    snapshot: State = self.state
    if snapshot.price_scale == 0:
        return [0, 0]
    fast: uint256 = 0
    slow: uint256 = 0
    fast, slow = self._project_emas(snapshot, self._observation(snapshot))
    return [fast, slow]


@internal
@view
def _observation(snapshot: State) -> uint256:
    """
    @dev What the EMAs and the target observe: the live report, else the pool's
         spot after the previous callback's operation, as in the pool's own EMA,
         so a touch cannot steer them with its own trade. Bounded to
         [scale / 2, 2 * scale].
    """
    price: uint256 = self._observed_report()
    if price == 0:
        price = snapshot.last_prices
    scale: uint256 = snapshot.price_scale
    return min(max(price, scale // 2), 2 * scale)


@internal
@view
def _observed_report() -> uint256:
    """
    @dev The stored report price while its age is below report_lifetime (separate
         from the fee's relax_time), else 0. A dropped report has price 0.
    """
    stored_report: Report = self.report
    if (
        stored_report.asset_price != 0
        and self._report_age_us(stored_report.observation_us)
        < self.config.driver.report_lifetime * 1_000_000
    ):
        return stored_report.asset_price
    return 0


@internal
@view
def _project_emas(snapshot: State, observation: uint256) -> (uint256, uint256):
    dt: uint256 = block.timestamp - snapshot.last_update_ts
    if dt == 0:  # Later touches of a block keep the EMAs.
        return snapshot.fast_ema, snapshot.slow_ema
    return (
        self._ema(snapshot.fast_ema, observation, dt, self.config.driver.fast_half_life),
        self._ema(snapshot.slow_ema, observation, dt, self.config.driver.slow_half_life),
    )


@internal
@pure
def _ema(ema: uint256, price: uint256, dt: uint256, half_life: uint256) -> uint256:
    # alpha = exp(-ln(2) * dt / half_life): the parameter is a true half-life.
    alpha: uint256 = convert(math._wad_exp(-convert(dt * LN2 // half_life, int256)), uint256)
    return (price * (PRECISION - alpha) + ema * alpha) // PRECISION


# ---------------------- Pool callback and LT deposit gate ----------------------


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
            gate LT deposits, settle the EMAs and store the snapshot, whose
            spot the next touch observes.
    @dev A balanced removal calls back best-effort with 300k gas: if this fails,
         the pool carries on with a stale snapshot when it had at least 500k gas
         before the call, and reverts otherwise. That path reads one pool value.
    """
    assert msg.sender == POOL, "auth!"

    snapshot: State = self.state
    # Gate first, against the previous snapshot: a revert unwinds an LT deposit.
    if not self.is_killed:
        self._update_lt_gate(xp[0], snapshot.xp[0])

    # The attachment callback seeds both EMAs with the pool's price_oracle.
    fast: uint256 = price_oracle
    slow: uint256 = price_oracle
    if snapshot.price_scale != 0:
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


@external
def sync():
    """
    @notice Re-read the pool's A, the fee snapshot's geometry and the LT gate's
            baselines; the EMAs wait for the next callback. Anyone may call:
            after a ramp's final pool checkpoint, a failed balanced-removal
            callback, or an LP gift to the LevAMM.
    """
    self._sync()


@internal
def _sync():
    """
    @dev Trusts LT, the LevAMM, the tokens and the oracle not to call sync
         during an unfinished LP transfer or book update.
    """
    # price_scale() is nonreentrant: this reverts inside a pool operation.
    price_scale: uint256 = staticcall Pool(POOL).price_scale()
    assert price_scale > 0, "pool uninitialized"
    self.cached_A = staticcall Pool(POOL).A()
    # Before attachment, leave the snapshot and supply for the attachment callback
    # to seed together.
    if self.state.price_scale != 0:
        self.cached_supply = staticcall Pool(POOL).user_supply()
        # As Twocrypto._xp computes it; coin0 has precision 1.
        precision1: uint256 = (staticcall Pool(POOL).precisions())[1]
        self.state.xp = [
            staticcall Pool(POOL).balances(0),
            staticcall Pool(POOL).balances(1) * precision1 * price_scale // PRECISION,
        ]
        self.state.D = staticcall Pool(POOL).D()
        self.state.price_scale = price_scale
    lp_balance: uint256 = staticcall Pool(POOL).balanceOf(AMM)
    collateral: uint256 = staticcall LevAMM(AMM).collateral_amount()
    self.amm_surplus = lp_balance - min(lp_balance, collateral)


@internal
def _update_lt_gate(stable: uint256, old_stable: uint256):
    """
    @dev LT.deposit(assets, debt) lets the caller pick the debt, and a debt off
         the LevAMM book's ratio is a fee-free trade against its holders. The
         fair deposit has

             debt == added_lp * old_debt / old_collateral

         LT mints the LP to the LevAMM, the pool calls back here, and only then
         does LT book it: the LevAMM still reports the old book, and a revert
         unwinds the deposit. added_lp is the growth of pool.user_supply(), and
         the debt the growth of xp[0], exact while the pool's admin fee is zero
         (checked at deployment). Should governance set one, the deposit's admin
         share goes unseen: an exact deposit can fail, and one can carry that
         share of extra debt beyond the tolerance.
    @param stable xp[0] of this callback: the pool's stablecoin balance
    @param old_stable xp[0] of the previous callback or sync
    """
    # Swaps and donations leave user LP supply unchanged.
    supply: uint256 = staticcall Pool(POOL).user_supply()
    old_supply: uint256 = self.cached_supply
    if supply == old_supply and old_supply != 0:
        return
    self.cached_supply = supply
    # Exits reduce booked collateral and LP holdings together, preserving gifts.
    if supply < old_supply:
        return

    # LP the LevAMM holds beyond its booked collateral: gifts, plus a deposit
    # minted but not yet booked.
    lp_balance: uint256 = staticcall Pool(POOL).balanceOf(AMM)
    collateral: uint256 = staticcall LevAMM(AMM).collateral_amount()
    surplus: uint256 = lp_balance - min(lp_balance, collateral)
    old_surplus: uint256 = self.amm_surplus

    # Nothing recorded yet: record only. At attachment the surplus is gifts. The
    # first add to an empty pool meets an empty book, whose LP is that add's own
    # unbooked LT deposit, not a gift.
    if old_supply == 0:
        if collateral == 0:
            surplus = 0
    else:
        added_lp: uint256 = supply - old_supply
        # An LT deposit leaves its minted LP unbooked on the LevAMM. An unrecorded
        # gift can make another add look like one, never the reverse.
        if surplus >= old_surplus + added_lp:
            surplus -= added_lp
            # An empty book has no ratio to keep and no holders to trade against.
            if collateral != 0:
                added_debt: uint256 = stable - min(stable, old_stable)
                proportional: uint256 = added_lp * staticcall LevAMM(AMM).get_debt() // collateral
                deviation: uint256 = (
                    added_debt - proportional
                    if added_debt > proportional
                    else proportional - added_debt
                )
                assert (
                    deviation * PRECISION <= proportional * self.config.ratio_tolerance
                ), "LT deviation"

    if surplus != old_surplus:
        self.amm_surplus = surplus


# -------------------------------- Pyth reports ---------------------------------


@external
@payable
@nonreentrant
def deliver_oracle_report(report_data: Bytes[112]):
    """
    @notice Verify and store a Pyth Lazer report; send verification_fee() as value.
    @dev Permissionless. Fees use the stored report while younger than relax_time,
         the EMAs while younger than report_lifetime.
    """
    assert not self.is_killed, "killed"
    # Establish the operation boundary before calling the external verifier.
    assert staticcall Pool(POOL).price_scale() > 0, "pool uninitialized"
    oracle: OracleConfig = self.oracle
    report_price: uint256 = 0
    observation_us: uint256 = 0
    message_us: uint256 = 0
    report_price, observation_us, message_us = self._verify_report(report_data, msg.value, oracle)

    # Observation age decides admission: a fresh message can carry an old price.
    block_time_us: uint256 = block.timestamp * 1_000_000
    assert (
        0 < observation_us
        and observation_us <= message_us
        and message_us <= block_time_us + oracle.future_window_us
    ), "report time"
    assert observation_us + oracle.past_window_us >= block_time_us, "report too old"
    # Strictly newer: no replay, including of a report dropped by set_killed.
    assert observation_us > self.report.observation_us, "observation not newer"
    assert oracle.min_price <= report_price and report_price <= oracle.max_price, "price bounds"

    self.report = Report(asset_price=report_price, observation_us=observation_us)
    log ReportAccepted(
        asset_price=report_price,
        observation_us=observation_us,
        message_us=message_us,
    )


@external
@view
def verification_fee() -> uint256:
    return staticcall PythLazer(self.oracle.verifier).verification_fee()


@internal
def _verify_report(
    report_data: Bytes[112], fee_paid: uint256, oracle: OracleConfig
) -> (uint256, uint256, uint256):
    """
    @dev Authenticate the report with Pyth and decode its payload.
    @return (coin1 price in USD 1e18, observation time us, message time us)
    """
    assert len(report_data) == 112, "report length"
    payload: Bytes[41] = b""
    signer: address = empty(address)
    payload, signer = extcall PythLazer(oracle.verifier).verifyUpdate(report_data, value=fee_paid)
    assert signer != empty(address), "signer"
    assert len(payload) == 41, "payload length"
    return self._decode_payload(payload, oracle)


@internal
@view
def _decode_payload(payload: Bytes[41], oracle: OracleConfig) -> (uint256, uint256, uint256):
    """
    @dev The payload must be one feed with exactly these properties. Big-endian
         byte ranges:
             [0:4]    magic                PYTH_PAYLOAD_MAGIC
             [4:12]   message time, us
             [12]     channel              oracle.channel
             [13]     feed count           1
             [14:18]  feed id              FEED_ID
             [18]     property count       3
             [19]     property id          0 (price)
             [20:28]  price mantissa       int64
             [28]     property id          4 (exponent)
             [29:31]  price exponent       int16
             [31]     property id          12 (feed update time)
             [32]     value present        1
             [33:41]  observation time, us
    @return (coin1 price in USD 1e18, observation time us, message time us)
    """
    assert convert(slice(payload, 0, 4), uint256) == PYTH_PAYLOAD_MAGIC, "payload magic"
    assert convert(slice(payload, 12, 1), uint8) == oracle.channel, "channel"
    assert slice(payload, 13, 1) == b"\x01", "one feed"
    assert convert(slice(payload, 14, 4), uint32) == FEED_ID, "feed"
    assert slice(payload, 18, 2) == b"\x03\x00", "price property"
    assert slice(payload, 28, 1) == b"\x04", "exponent property"
    assert slice(payload, 31, 2) == b"\x0c\x01", "observation property"

    mantissa: int64 = convert(convert(slice(payload, 20, 8), bytes8), int64)
    exponent: int16 = convert(convert(slice(payload, 29, 2), bytes2), int16)
    assert mantissa > 0 and -18 <= exponent and exponent <= 0, "price/exponent"
    report_price: uint256 = convert(mantissa, uint256) * 10**convert(18 + exponent, uint256)

    message_us: uint256 = convert(slice(payload, 4, 8), uint256)
    observation_us: uint256 = convert(slice(payload, 33, 8), uint256)
    return report_price, observation_us, message_us


@internal
@view
def _report_age_us(observation_us: uint256) -> uint256:
    """A report observed after block.timestamp has age zero."""
    block_time_us: uint256 = block.timestamp * 1_000_000
    return block_time_us - min(block_time_us, observation_us)


# --------------------------------- Governance ----------------------------------


@external
def set_policy_config(config: PolicyConfig):
    """
    @notice Replace the whole policy config. Owner only.
    @dev No EMA checkpoint: new half-lives apply to the whole interval since the
         last touch, and raising relax_time or report_lifetime can revive a
         stored report.
    """
    ownable._check_owner()
    self._set_policy_config(config)


@external
def set_oracle_config(oracle: OracleConfig):
    """
    @notice Set report admission: verifier, channel, age windows and price
            bounds. Owner only.
    @dev The verifier decides which prices are authentic, so the owner holds
         that trust. Every call drops the stored report price; its observation
         time stays as the replay watermark, and the kill state is unchanged.
    """
    ownable._check_owner()
    self._set_oracle_config(oracle)
    self.report.asset_price = 0


@external
def set_killed(is_killed: bool):
    """
    @notice Kill (True) or revive the policy. Owner or emergency admin.
    @dev While killed, get_fee and get_price_scale return 0 (the pool's native
         fee and target), reports are refused and the LT gate is off, external
         reads included. Callbacks still settle the EMAs. Killing drops the
         stored report price and keeps its watermark; reviving calls sync().
    """
    assert msg.sender == EMERGENCY_ADMIN or msg.sender == ownable.owner, "access"
    if is_killed:
        self.report.asset_price = 0
    else:
        self._sync()
    self.is_killed = is_killed
    log SetKilled(is_killed=is_killed)


@internal
def _set_policy_config(config: PolicyConfig):
    fee: FeeConfig = config.fee
    assert fee.base_fee >= MIN_FEE and fee.base_fee <= fee.fallback_fee, "base fee"
    assert fee.fallback_fee <= FEE_PRECISION // 10, "fallback fee"  # 10%
    assert fee.capture <= PRECISION, "capture"
    assert fee.relax_time > 0 and fee.relax_time <= 3_600, "relax time"  # 1 hour

    driver: DriverConfig = config.driver
    # Half-lives from 10 minutes to a week, fast at most slow.
    assert (
        driver.fast_half_life >= 600 and driver.fast_half_life <= driver.slow_half_life
    ), "fast half-life"
    assert driver.slow_half_life <= 604_800, "slow half-life"
    assert driver.trend_gate <= PRECISION // 10, "trend gate"  # 10%
    # Up to 60 bp per touch: a requested gap of at most 3% of price_scale.
    assert driver.step_cap > 0 and driver.step_cap <= 60 * PRECISION // 10_000, "step cap"
    assert driver.report_lifetime <= 14_400, "report lifetime"  # 4 hours

    assert config.ratio_tolerance <= PRECISION // 1000, "ratio tolerance"  # 10 bp

    self.config = config
    log SetPolicyConfig(config=config)


@internal
def _set_oracle_config(oracle: OracleConfig):
    assert oracle.verifier.is_contract, "verifier"
    # The four channels Pyth Lazer defines (PythLazerStructs.Channel).
    assert oracle.channel >= 1 and oracle.channel <= 4, "channel"
    assert oracle.past_window_us <= MAX_PAST_WINDOW_US, "past window"
    assert oracle.future_window_us <= MAX_FUTURE_WINDOW_US, "future window"
    assert (
        MIN_REPORT_PRICE <= oracle.min_price
        and oracle.min_price <= oracle.max_price
        and oracle.max_price <= MAX_REPORT_PRICE
    ), "price bounds"
    self.oracle = oracle
    log SetOracleConfig(oracle=oracle)


# ----------------------------------- Quotes ------------------------------------


@external
@view
def get_dy_with_report(
    i: uint256, j: uint256, dx: uint256, report_data: Bytes[112], block_timestamp: uint256
) -> uint256:
    """
    @notice pool.get_dy(i, j, dx) with this signed report stored, its age taken
            at block_timestamp (say the next block's).
    @dev A convenience view: the signature is not verified and the report is not
         admitted, only decoded. The pool's state, A included, is this block's.
    """
    report_price: uint256 = 0
    observation_us: uint256 = 0
    message_us: uint256 = 0
    report_price, observation_us, message_us = self._decode_payload(
        slice(report_data, 71, 41), self.oracle
    )
    now_us: uint256 = block_timestamp * 1_000_000
    return self._quote(i, j, dx, report_price, now_us - min(now_us, observation_us))


@external
@view
def get_dy_with_report_age(
    i: uint256, j: uint256, dx: uint256, report_price: uint256, report_age_us: uint256
) -> uint256:
    """
    @notice pool.get_dy(i, j, dx) with a stored report of this price (1e18 = $1)
            observed report_age_us before the block; pass age 0 for an
            observation after block.timestamp.
    """
    return self._quote(i, j, dx, report_price, report_age_us)


# TwocryptoView.get_dy with the pool's state read directly. Like it, during an A
# ramp the quote can keep a discount that the swap loses (see _get_fee).
@internal
@view
def _quote(
    i: uint256, j: uint256, dx: uint256, report_price: uint256, report_age_us: uint256
) -> uint256:
    assert i != j and i < N_COINS and j < N_COINS, "coin index out of range"
    # A detached policy no longer prices the pool's swaps.
    assert staticcall Pool(POOL).POLICY() == self, "not attached"

    math_contract: Math = staticcall Pool(POOL).MATH()
    precisions: uint256[N_COINS] = staticcall Pool(POOL).precisions()
    xp: uint256[N_COINS] = [staticcall Pool(POOL).balances(0), staticcall Pool(POOL).balances(1)]
    price_scale: uint256 = staticcall Pool(POOL).price_scale()
    A: uint256 = staticcall Pool(POOL).A()
    gamma: uint256 = staticcall Pool(POOL).gamma()

    D: uint256 = staticcall Pool(POOL).D()
    if staticcall Pool(POOL).future_A_gamma_time() > staticcall Pool(POOL).last_timestamp():
        ramp_xp: uint256[N_COINS] = [
            xp[0] * precisions[0], xp[1] * price_scale * precisions[1] // PRECISION
        ]
        D = staticcall math_contract.newton_D(A, gamma, ramp_xp, 0)

    xp[i] += dx
    xp = [xp[0] * precisions[0], xp[1] * price_scale * precisions[1] // PRECISION]

    y_out: uint256[2] = staticcall math_contract.get_y(A, gamma, xp, D, j)
    assert y_out[0] < xp[j], "unsafe value for y"
    dy: uint256 = xp[j] - y_out[0] - 1
    xp[j] = y_out[0]
    if j > 0:
        dy = dy * PRECISION // price_scale
    dy //= precisions[j]

    fee: uint256 = self._get_fee(xp, report_price, report_age_us)
    if fee == 0:  # Killed: the pool's native fee.
        fee = staticcall Pool(POOL).fee_calc(xp)
    # The pool clamps fees to [MIN_FEE, FEE_PRECISION]; config bounds keep this one inside.
    return dy - fee * dy // FEE_PRECISION
