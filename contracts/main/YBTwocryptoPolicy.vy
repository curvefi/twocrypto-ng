# pragma version 0.4.3
# pragma optimize gas
"""
@title YBTwocryptoPolicy
@notice Policy-owned dual-EMA price-scale controller for YieldBasis Twocrypto pools.
@dev Each authenticated pool touch settles both EMAs toward the preceding
     last_prices observation, stores the new observation, and restarts a
     one-hour linear cap ramp. The deadband and cap apply to the raw relative
     gap between the current scale and dual-EMA target. Only the final capped
     gap is multiplied by five for Twocrypto's downstream actuator.
     get_fee returns 0 so the pool keeps its native dynamic fee.
"""
from snekmate.utils import math

N_COINS: constant(uint256) = 2
PRECISION: constant(uint256) = 10**18
BPS_SCALE: constant(uint256) = 10_000
LN2: constant(uint256) = 693_147_180_559_945_309
TWEAK_PRICE_MULTIPLIER: constant(uint256) = 5
CAP_RAMP_SECONDS: constant(uint256) = 3_600

POOL: public(immutable(address))
FAST_HALF_LIFE: public(immutable(uint256))
SLOW_HALF_LIFE: public(immutable(uint256))
KAPPA: public(immutable(uint256))  # 1e18 gain: 0 = slow, 1e18 = fast
DEADBAND_BPS: public(immutable(uint256))  # 1e18 = 1 bp
MIN_CAP_BPS: public(immutable(uint256))  # 1e18 = 1 bp
MAX_CAP_BPS: public(immutable(uint256))  # 1e18 = 1 bp

struct State:
    last_update_ts: uint256
    last_prices: uint256
    fast_ema: uint256
    slow_ema: uint256
    price_scale: uint256

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
    # Bound EMA memory to 10 minutes .. 1 week; equality is a useful one-EMA mode.
    assert fast_half_life >= 600 and fast_half_life <= 604_800, "fast half-life"
    assert slow_half_life >= 600 and slow_half_life <= 604_800, "slow half-life"
    assert fast_half_life <= slow_half_life, "half-life order"
    assert kappa <= 2 * PRECISION, "kappa"
    # BPS knobs have 1e18 fractional precision: 10e18 means 10 bps.
    assert deadband_bps <= 60 * PRECISION, "deadband"
    assert max_cap_bps <= 60 * PRECISION, "max cap"
    assert min_cap_bps >= PRECISION and min_cap_bps <= max_cap_bps, "min cap"

    POOL = pool
    FAST_HALF_LIFE = fast_half_life
    SLOW_HALF_LIFE = slow_half_life
    KAPPA = kappa
    DEADBAND_BPS = deadband_bps
    MIN_CAP_BPS = min_cap_bps
    MAX_CAP_BPS = max_cap_bps


@external
@pure
def get_fee(_xp: uint256[N_COINS]) -> uint256:
    """@notice Return 0 to use Twocrypto's native mid/out fee curve."""
    return 0


@external
@view
def get_emas() -> uint256[2]:
    """@return The projected [fast EMA, slow EMA] at the current timestamp."""
    snapshot: State = self.state
    if snapshot.price_scale == 0:
        return [0, 0]
    return self._project_emas(snapshot, block.timestamp - snapshot.last_update_ts)


@external
@view
def get_price_scale() -> uint256:
    """@notice Return a compensated target for Twocrypto, or 0 before initialization."""
    snapshot: State = self.state
    current: uint256 = snapshot.price_scale
    if current == 0:
        return 0

    elapsed: uint256 = block.timestamp - snapshot.last_update_ts
    ramp_time: uint256 = min(elapsed, CAP_RAMP_SECONDS)

    # Fractional-bps policy thresholds: 10e18 means 10 bps.
    current_cap: uint256 = MIN_CAP_BPS + (
        (MAX_CAP_BPS - MIN_CAP_BPS) * ramp_time // CAP_RAMP_SECONDS
    )
    deadband: uint256 = DEADBAND_BPS

    emas: uint256[2] = self._project_emas(snapshot, elapsed)
    fast: uint256 = emas[0]
    slow: uint256 = emas[1]

    # Extrapolate from slow toward fast; fall back to fast instead of underflowing.
    raw_target: uint256 = 0
    if fast >= slow:
        raw_target = slow + KAPPA * (fast - slow) // PRECISION
    else:
        bearish_step: uint256 = KAPPA * (slow - fast) // PRECISION
        raw_target = slow - bearish_step if bearish_step < slow else fast

    ema_gap: uint256 = (
        raw_target - current if raw_target >= current else current - raw_target
    )

    # Compare the raw relative target gap with the inclusive deadband without
    # division or precision loss.
    if ema_gap * BPS_SCALE * PRECISION <= current * deadband:
        return current

    max_move: uint256 = current * current_cap // (BPS_SCALE * PRECISION)
    desired_move: uint256 = min(ema_gap, max_move)

    # Twocrypto requests one-fifth of its target gap, so compensate only here.
    target_gap: uint256 = TWEAK_PRICE_MULTIPLIER * desired_move
    # Constructor bounds limit target_gap to 5 * 60 bps = 3% of current.
    return current + target_gap if raw_target >= current else current - target_gap


@external
def update_pool_state(
    _xp: uint256[N_COINS],
    price_scale: uint256,
    price_oracle: uint256,
    last_prices: uint256,
    _virtual_price: uint256,
    _xcp_profit: uint256,
    _D: uint256,
    _oracle_timestamp: uint256,
):
    """@notice Settle the EMAs and store the latest authenticated pool snapshot."""
    assert msg.sender == POOL, "auth!"

    previous: State = self.state
    fast: uint256 = price_oracle
    slow: uint256 = price_oracle
    if previous.price_scale != 0:
        # Settle toward the preceding sample before storing the new one.
        emas: uint256[2] = self._project_emas(
            previous, block.timestamp - previous.last_update_ts
        )
        fast = emas[0]
        slow = emas[1]

    self.state = State(
        last_update_ts=block.timestamp,
        last_prices=last_prices,
        fast_ema=fast,
        slow_ema=slow,
        price_scale=price_scale,
    )


@internal
@view
def _project_emas(snapshot: State, dt: uint256) -> uint256[2]:
    return [
        self._ema(
            snapshot.fast_ema, snapshot.last_prices, snapshot.price_scale, dt, FAST_HALF_LIFE
        ),
        self._ema(
            snapshot.slow_ema, snapshot.last_prices, snapshot.price_scale, dt, SLOW_HALF_LIFE
        ),
    ]


@internal
@pure
def _ema(
    ema: uint256,
    last_prices: uint256,
    price_scale: uint256,
    dt: uint256,
    half_life: uint256,
) -> uint256:
    if dt == 0:
        return ema

    # Bound one observation to [scale / 2, 2 * scale].
    price: uint256 = min(max(last_prices, price_scale // 2), 2 * price_scale)
    # alpha = exp(-ln(2) * dt / half_life): the parameter is a true half-life.
    alpha: uint256 = convert(
        math._wad_exp(-convert(dt * LN2 // half_life, int256)),
        uint256,
    )
    return (price * (PRECISION - alpha) + ema * alpha) // PRECISION
