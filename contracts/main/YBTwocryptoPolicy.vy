# pragma version 0.4.3
# pragma optimize gas
"""
@title YBTwocryptoPolicy
@notice Dual-EMA price-scale policy for BTC/USD YieldBasis twocrypto pools.
@dev Advances independent fast and slow EMAs toward the pool's clamped last price.
     The target extrapolates from slow toward fast by KAPPA, is deadbanded, and
     is capped by a MIN-to-MAX actuator allowance that ramps over one hour.
     Zero fee and uninitialized target outputs defer to Twocrypto's native logic.
     Checked-math overhead is negligible beside policy call and storage costs.
"""
from snekmate.utils import math

N_COINS: constant(uint256) = 2
PRECISION: constant(uint256) = 10**18
BPS_SCALE: constant(uint256) = 10_000
LN2: constant(uint256) = 693_147_180_559_945_309
CAP_RAMP_MINUTES: constant(uint256) = 60

POOL: public(immutable(address))
FAST_HALF_LIFE: public(immutable(uint256))
SLOW_HALF_LIFE: public(immutable(uint256))
KAPPA: public(immutable(uint256))
DEADBAND_BPS: public(immutable(uint256))
MIN_CAP_BPS: public(immutable(uint256))
MAX_CAP_BPS: public(immutable(uint256))

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

    POOL = pool
    FAST_HALF_LIFE = fast_half_life
    SLOW_HALF_LIFE = slow_half_life
    KAPPA = kappa
    DEADBAND_BPS = deadband_bps
    MIN_CAP_BPS = min_cap_bps
    MAX_CAP_BPS = max_cap_bps


@external
@view
def get_fee(xp: uint256[N_COINS]) -> uint256:
    """@notice Always return 0 so Twocrypto uses its native fee logic."""
    return 0


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
    dt: uint256 = block.timestamp - state.last_update_ts
    emas: uint256[2] = self._get_emas(state, dt)
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
    # The bps-discrete cap interpolates from MIN to MAX over CAP_RAMP_MINUTES.
    minutes_since_update: uint256 = min(dt // 60, CAP_RAMP_MINUTES)
    cap_bps: uint256 = MIN_CAP_BPS + (
        (MAX_CAP_BPS - MIN_CAP_BPS) * minutes_since_update // CAP_RAMP_MINUTES
    )
    max_step: uint256 = current_scale * 5 * cap_bps // BPS_SCALE
    target = min(
        max(target, current_scale - max_step),
        current_scale + max_step,
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

    emas: uint256[2] = self._get_emas(state, block.timestamp - state.last_update_ts)
    state.last_update_ts = block.timestamp
    state.last_prices = last_prices
    state.fast_ema = emas[0]
    state.slow_ema = emas[1]
    state.pool_price_scale = price_scale
    self.state = state


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
