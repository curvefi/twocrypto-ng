# pragma version 0.4.3
# pragma optimize gas
"""
@title YBTwocryptoPolicy
@notice Dual-EMA price-scale policy for BTC/USD YieldBasis twocrypto pools.
@dev Advances independent fast and slow EMAs toward the pool's clamped last price.
     The target extrapolates from slow toward fast by KAPPA, is capped by an
     actuator allowance ramping from MIN_CAP_BPS to MAX_CAP_BPS over
     CAP_RAMP_SECONDS since the last pool touch, then deadbanded.
     get_fee reprices Twocrypto's skew fee with the policy's own parameters;
     after CALM_SECONDS idle it decays linearly over FEE_RAMP_SECONDS down to
     the MIN_DYNAMIC_FEE floor to attract a re-aligning trade.
     Before the first pool update every output is 0, deferring to native logic.
     Checked-math overhead is negligible beside policy call and storage costs.
"""
from snekmate.utils import math

N_COINS: constant(uint256) = 2
PRECISION: constant(uint256) = 10**18
BPS_SCALE: constant(uint256) = 10_000
LN2: constant(uint256) = 693_147_180_559_945_309
FEE_PRECISION: constant(uint256) = 10**10  # mirrors Twocrypto fee precision
MIN_FEE: constant(uint256) = FEE_PRECISION * 1 // 10 // 10_000  # 0.1 BPS.
MAX_FEE: constant(uint256) = FEE_PRECISION

POOL: public(immutable(address))
FAST_HALF_LIFE: public(immutable(uint256))
SLOW_HALF_LIFE: public(immutable(uint256))
KAPPA: public(immutable(uint256))  # 1e18 gain: 0 = track slow, 1e18 = fast, <=2e18 beyond fast
DEADBAND_BPS: public(immutable(uint256))
MIN_CAP_BPS: public(immutable(uint256))
MAX_CAP_BPS: public(immutable(uint256))
CAP_RAMP_SECONDS: public(immutable(uint256))
MID_FEE: public(immutable(uint256))
OUT_FEE: public(immutable(uint256))
FEE_GAMMA: public(immutable(uint256))
MIN_DYNAMIC_FEE: public(immutable(uint256))  # in FEE_PRECISION units, like MID/OUT_FEE
CALM_SECONDS: public(immutable(uint256))
FEE_RAMP_SECONDS: public(immutable(uint256))

struct State:
    last_update_ts: uint256
    last_prices: uint256  # mirrors Twocrypto's singular field name
    fast_ema: uint256
    slow_ema: uint256
    pool_price_scale: uint256

# Snapshot settled on each pool update.
state: public(State)


@deploy
def __init__(
    pool: address,
    fast_half_life: uint256,
    slow_half_life: uint256,
    kappa: uint256,
    deadband_bps: uint256,
    min_cap_bps: uint256,
    max_cap_bps: uint256,
    cap_ramp_seconds: uint256,
    mid_fee: uint256,
    out_fee: uint256,
    fee_gamma: uint256,
    min_dynamic_fee: uint256,
    calm_seconds: uint256,
    fee_ramp_seconds: uint256,
):
    assert pool != empty(address), "pool=0"
    # EMA half-lives are bounded to 10 minutes .. 1 week.
    assert fast_half_life >= 600 and fast_half_life <= 604_800, "fast half-life"
    assert slow_half_life >= 600 and slow_half_life <= 604_800, "slow half-life"
    assert kappa <= 2 * PRECISION, "kappa"
    # Deadband and the native actuator allowance are each bounded to 0.6%.
    assert deadband_bps <= 60, "deadband"
    assert max_cap_bps <= 60, "max cap"
    assert min_cap_bps <= max_cap_bps, "min cap"
    assert cap_ramp_seconds >= 60 and cap_ramp_seconds <= 604_800, "cap ramp"
    # mid/out fee bounds mirror Twocrypto's constructor validation.
    assert mid_fee >= MIN_FEE, "mid fee"
    assert out_fee >= mid_fee and out_fee <= MAX_FEE, "out fee"
    # fee_gamma bounds follow Twocrypto's apply_new_parameters, which cannot
    # set exactly 1e18 (its keep-current sentinel); 1e18 is allowed here and
    # makes the slope regulation an identity.
    assert fee_gamma >= 1 and fee_gamma <= PRECISION, "fee gamma"
    # The decay floor must be within [MIN_FEE, mid_fee]: at least the pool's
    # own minimum (it clamps anything lower, and nonzero output keeps the 0
    # sentinel unreachable), at most mid_fee so the skew curve, not the
    # floor, prices a balanced pool.
    assert min_dynamic_fee >= MIN_FEE and min_dynamic_fee <= mid_fee, "min fee"
    # Calm is bounded to 1 week; the fee ramp to 1 minute .. 1 week.
    assert calm_seconds <= 604_800, "calm"
    assert fee_ramp_seconds >= 60 and fee_ramp_seconds <= 604_800, "fee ramp"

    POOL = pool
    FAST_HALF_LIFE = fast_half_life
    SLOW_HALF_LIFE = slow_half_life
    KAPPA = kappa
    DEADBAND_BPS = deadband_bps
    MIN_CAP_BPS = min_cap_bps
    MAX_CAP_BPS = max_cap_bps
    CAP_RAMP_SECONDS = cap_ramp_seconds
    MID_FEE = mid_fee
    OUT_FEE = out_fee
    FEE_GAMMA = fee_gamma
    MIN_DYNAMIC_FEE = min_dynamic_fee
    CALM_SECONDS = calm_seconds
    FEE_RAMP_SECONDS = fee_ramp_seconds


@external
@view
def get_fee(xp: uint256[N_COINS]) -> uint256:
    """@notice Idle-decayed skew fee, or 0 (native fee) before the first pool update."""
    state: State = self.state
    if state.pool_price_scale == 0:
        return 0

    # After CALM_SECONDS idle, decay linearly over FEE_RAMP_SECONDS from the
    # skew fee down to the MIN_DYNAMIC_FEE floor to attract a re-aligning trade.
    fee: uint256 = self._skew_fee(xp)
    idle: uint256 = block.timestamp - state.last_update_ts
    if idle > CALM_SECONDS:
        fee_decay_progress: uint256 = self._linear_ramp(
            idle - CALM_SECONDS, FEE_RAMP_SECONDS, 0, BPS_SCALE
        )
        # Discount a progress fraction of the decayable gap; safe because the
        # constructor bounds MIN_DYNAMIC_FEE by mid_fee <= skew fee.
        discount: uint256 = (fee - MIN_DYNAMIC_FEE) * fee_decay_progress // BPS_SCALE
        fee -= discount
    # fee >= MIN_DYNAMIC_FEE >= MIN_FEE > 0: the 0 sentinel is unreachable.
    return fee


@external
@view
def get_emas() -> uint256[2]:
    """@return Projected [fast_ema, slow_ema] at the current timestamp."""
    state: State = self.state
    if state.pool_price_scale == 0:
        return [0, 0]
    return self._get_emas(state, block.timestamp - state.last_update_ts)


@external
@view
def get_price_scale() -> uint256:
    """@notice Return the policy target, or 0 before the first pool update."""
    state: State = self.state
    if state.pool_price_scale == 0:
        return 0

    current_scale: uint256 = state.pool_price_scale
    idle: uint256 = block.timestamp - state.last_update_ts
    emas: uint256[2] = self._get_emas(state, idle)
    fast_ema: uint256 = emas[0]
    slow_ema: uint256 = emas[1]

    # ---- Dual-EMA target: slow + KAPPA * (fast - slow).
    target: uint256 = 0
    if fast_ema >= slow_ema:
        target = slow_ema + KAPPA * (fast_ema - slow_ema) // PRECISION
    else:
        step: uint256 = KAPPA * (slow_ema - fast_ema) // PRECISION
        # If extrapolation underflows, degrade to fast: the spot-tracking EMA.
        target = slow_ema - step if step < slow_ema else fast_ema

    # ---- Staleness-ramped native actuator cap.
    # Mirrors Twocrypto tweak_price's hardcoded norm / 5 actuator: a
    # 5 * cap_bps target gap becomes at most a cap_bps price-scale step.
    # Unlike the fee ramp, the cap has no calm period (calm = 0): it grows
    # from MIN_CAP_BPS immediately after the last pool touch.
    cap_bps: uint256 = self._linear_ramp(idle, CAP_RAMP_SECONDS, MIN_CAP_BPS, MAX_CAP_BPS)
    max_target_gap: uint256 = current_scale * 5 * cap_bps // BPS_SCALE
    target = min(
        max(target, current_scale - max_target_gap),
        current_scale + max_target_gap,
    )

    # ---- Deadband: return a nonzero hold target.
    delta: uint256 = target - current_scale if target >= current_scale else current_scale - target
    if DEADBAND_BPS > 0 and delta * BPS_SCALE // current_scale <= DEADBAND_BPS:
        return current_scale
    return target


@external
def update_pool_state(
    xp: uint256[N_COINS],
    price_scale: uint256,
    price_oracle: uint256,
    last_prices: uint256,
    virtual_price: uint256,
    xcp_profit: uint256,
    D: uint256,
    oracle_timestamp: uint256,
):
    """@notice Settle both EMAs and store the latest authenticated pool state."""
    # xp, virtual_price, xcp_profit, D, and oracle_timestamp are unused but
    # required by Twocrypto's policy callback ABI.
    assert msg.sender == POOL, "auth!"

    state: State = self.state
    if state.pool_price_scale == 0:
        # First pool update: seed both EMAs from Twocrypto's oracle.
        self.state = State(
            last_update_ts=block.timestamp,
            last_prices=last_prices,
            fast_ema=price_oracle,
            slow_ema=price_oracle,
            pool_price_scale=price_scale,
        )
        return

    # Settled update: same shape as the seed above, differing only in the
    # EMA source (settled from the previous observation instead of seeded).
    emas: uint256[2] = self._get_emas(state, block.timestamp - state.last_update_ts)
    self.state = State(
        last_update_ts=block.timestamp,
        last_prices=last_prices,
        fast_ema=emas[0],
        slow_ema=emas[1],
        pool_price_scale=price_scale,
    )


@internal
@pure
def _linear_ramp(dt: uint256, ramp_seconds: uint256, from_bps: uint256, to_bps: uint256) -> uint256:
    # Linear from_bps -> to_bps as dt goes 0 -> ramp_seconds, then flat.
    # Callers guarantee ramp_seconds > 0 and to_bps >= from_bps.
    return from_bps + (to_bps - from_bps) * min(dt, ramp_seconds) // ramp_seconds


@internal
@view
def _skew_fee(xp: uint256[N_COINS]) -> uint256:
    # Twocrypto's _fee formula with the policy's own MID_FEE/OUT_FEE/FEE_GAMMA.
    # B is a balance indicator: 10**18 at perfect balance, approaching 0 as
    # imbalance grows (~0.04e18 at 100:1): N^N * xp[0] * xp[1] / (xp[0] + xp[1])**2.
    B: uint256 = xp[0] + xp[1]
    B = PRECISION * N_COINS**N_COINS * xp[0] // B * xp[1] // B
    # Regulate slope: fee_gamma * B / (fee_gamma * B + 1 - B).
    B = FEE_GAMMA * B // (FEE_GAMMA * B // PRECISION + PRECISION - B)
    # mid_fee * B + out_fee * (1 - B).
    return (MID_FEE * B + OUT_FEE * (PRECISION - B)) // PRECISION


@internal
@view
def _get_emas(state: State, dt: uint256) -> uint256[2]:
    return [
        self._ema(state.fast_ema, state.last_prices, state.pool_price_scale, dt, FAST_HALF_LIFE),
        self._ema(state.slow_ema, state.last_prices, state.pool_price_scale, dt, SLOW_HALF_LIFE),
    ]


@internal
@pure
def _ema(
    ema: uint256,
    last_prices: uint256,
    pool_price_scale: uint256,
    dt: uint256,
    half_life: uint256,
) -> uint256:
    if dt == 0:
        return ema

    # Clamp Twocrypto's last spot price to [scale / 2, 2 * scale] so one
    # manipulated observation cannot yank either EMA.
    last_prices = min(
        max(last_prices, pool_price_scale // 2),
        2 * pool_price_scale,
    )
    # Half-life convention: Twocrypto's ma_time equals half_life / ln(2).
    # alpha = exp(-dt * ln(2) / half_life).
    # new = alpha * old + (1 - alpha) * price.
    alpha: uint256 = convert(
        math._wad_exp(-convert(dt * LN2 // half_life, int256)),
        uint256,
    )
    return (last_prices * (PRECISION - alpha) + ema * alpha) // PRECISION
