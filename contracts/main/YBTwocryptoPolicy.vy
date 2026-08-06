# pragma version 0.4.3
# pragma optimize gas
"""
@title YBTwocryptoPolicy
@notice Policy-owned dual-EMA price-scale controller for YieldBasis Twocrypto pools.
@dev Each authenticated pool touch settles both EMAs toward the preceding
     last_prices observation, stores the new observation, and restarts a
     one-hour linear cap ramp. The deadband and cap are expressed in bps of
     intended price-scale movement; returned targets are five times farther
     because Twocrypto's native actuator moves one-fifth of the target gap.
     get_fee returns 0 so the pool keeps its native dynamic fee.
"""
from snekmate.utils import math

N_COINS: constant(uint256) = 2
PRECISION: constant(uint256) = 10**18
BPS_SCALE: constant(uint256) = 10_000
LN2: constant(uint256) = 693_147_180_559_945_309
ACTUATOR_DIVISOR: constant(uint256) = 5
CAP_RAMP_SECONDS: constant(uint256) = 3_600

POOL: public(immutable(address))
FAST_HALF_LIFE: public(immutable(uint256))
SLOW_HALF_LIFE: public(immutable(uint256))
KAPPA: public(immutable(uint256))  # 1e18: slow + KAPPA * (fast - slow)
DEADBAND_BPS: public(immutable(uint256))
MIN_CAP_BPS: public(immutable(uint256))
MAX_CAP_BPS: public(immutable(uint256))

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
    # Deadband and cap knobs describe native movement, not the 5x target gap.
    assert deadband_bps <= 60, "deadband"
    assert max_cap_bps <= 60, "max cap"
    assert min_cap_bps >= 1 and min_cap_bps <= max_cap_bps, "min cap"

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
    """@notice Return the capped EMA target, or 0 until the pool initializes the policy."""
    snapshot: State = self.state
    current: uint256 = snapshot.price_scale
    if current == 0:
        return 0

    elapsed: uint256 = block.timestamp - snapshot.last_update_ts
    ramp_time: uint256 = min(elapsed, CAP_RAMP_SECONDS)

    # Relative native-move thresholds in 1e18 precision, where 1e18 is 100%.
    min_cap: uint256 = MIN_CAP_BPS * PRECISION // BPS_SCALE
    max_cap: uint256 = MAX_CAP_BPS * PRECISION // BPS_SCALE
    current_cap: uint256 = min_cap + (
        (max_cap - min_cap) * ramp_time // CAP_RAMP_SECONDS
    )
    deadband: uint256 = DEADBAND_BPS * PRECISION // BPS_SCALE

    emas: uint256[2] = self._project_emas(snapshot, elapsed)
    fast: uint256 = emas[0]
    slow: uint256 = emas[1]

    # Extrapolate from slow toward fast; fall back to fast instead of underflowing.
    target: uint256 = 0
    if fast >= slow:
        target = slow + KAPPA * (fast - slow) // PRECISION
    else:
        bearish_step: uint256 = KAPPA * (slow - fast) // PRECISION
        target = slow - bearish_step if bearish_step < slow else fast

    raw_gap: uint256 = target - current if target >= current else current - target

    # Native requested move = raw_gap / current / 5. Cross-multiply so the
    # inclusive deadband comparison does not lose precision.
    if raw_gap * PRECISION <= current * ACTUATOR_DIVISOR * deadband:
        return current

    # The policy target must be 5x farther away to produce current_cap natively.
    allowed_gap: uint256 = current * ACTUATOR_DIVISOR * current_cap // PRECISION

    return min(max(target, current - allowed_gap), current + allowed_gap)


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
