# pragma version 0.4.3
# pragma optimize gas
"""
@title YBOraclizedPolicy
@notice Policy-owned dual-EMA price-scale controller for YieldBasis Twocrypto pools.
@dev Each authenticated pool touch settles both EMAs toward the preceding
     last_prices observation, stores the new observation, and restarts a
     one-hour linear cap ramp. The deadband and cap apply to the raw relative
     gap between the current scale and dual-EMA target. Only the final capped
     gap is multiplied by five for Twocrypto's downstream actuator.
     get_fee adds Pyth edge discounts with square-root report-age inflation.
     Reports do not modify the dual-EMA driver.
"""
from snekmate.utils import math

N_COINS: constant(uint256) = 2
PRECISION: constant(uint256) = 10**18
LN2: constant(uint256) = 693_147_180_559_945_309
TWEAK_PRICE_MULTIPLIER: constant(uint256) = 5
CAP_RAMP_SECONDS: constant(uint256) = 3_600

POOL: public(immutable(address))
FAST_HALF_LIFE: public(immutable(uint256))
SLOW_HALF_LIFE: public(immutable(uint256))
KAPPA: public(immutable(uint256))  # 1e18 gain: 0 = slow, 1e18 = fast
# Relative WADs: 1e18 = 100%.
DEADBAND: public(immutable(uint256))
MIN_CAP: public(immutable(uint256))
MAX_CAP: public(immutable(uint256))

struct State:
    last_update_ts: uint256
    last_prices: uint256
    fast_ema: uint256
    slow_ema: uint256
    price_scale: uint256
    xp: uint256[N_COINS]
    D: uint256

state: public(State)


# ------------------------ Report-based fee configuration ----------------------

interface PythLazer:
    def verification_fee() -> uint256: view
    def verifyUpdate(report: Bytes[112]) -> (Bytes[41], address): payable


interface Pool:
    def price_scale() -> uint256: view  # Guarded: only outside a pool operation.
    def D() -> uint256: view
    def A() -> uint256: view
    def future_A_gamma_time() -> uint256: view

A_MULTIPLIER: constant(uint256) = 10000
FEE_PRECISION: constant(uint256) = 10**10
MIN_PRICE: constant(uint256) = 10**6
MAX_PRICE: constant(uint256) = 10**30
FEE_CAP: public(constant(uint256)) = FEE_PRECISION

PYTH: public(immutable(address))
FEED_ID: public(immutable(uint32))
CHANNEL: public(immutable(uint8))
POOL_A: public(uint256)

struct Parameters:
    fallback_fee: uint256  # Raw fee when informed pricing is unavailable.
    base_fee: uint256  # Minimum informed raw fee.
    capture: uint256  # PRECISION fraction of reported edge above the base fee.
    max_report_age_ms: uint256
    report_expiry_s: uint256  # Observation age at which swap fees reach fallback.


struct Report:
    asset_price: uint256  # Pyth USD price; fees assume coin0 is worth one USD.
    observation_us: uint256
    message_us: uint256
    delivered_at: uint256
    delivered_in_block: uint256


parameters: public(Parameters)  # Set only at deployment.
report: public(Report)


event ReportAccepted:
    asset_price: uint256  # Pyth USD price; fees assume coin0 is worth one USD.
    observation_us: uint256
    message_us: uint256


@deploy
def __init__(
    pool: address,
    fast_half_life: uint256,
    slow_half_life: uint256,
    kappa: uint256,
    deadband: uint256,
    min_cap: uint256,
    max_cap: uint256,
    pyth: address,
    feed_id: uint32,
    channel: uint8,
    params: Parameters,
):
    assert pool != empty(address), "pool=0"
    # Bound EMA memory to 10 minutes .. 1 week; equality is a useful one-EMA mode.
    assert fast_half_life >= 600 and fast_half_life <= 604_800, "fast half-life"
    assert slow_half_life >= 600 and slow_half_life <= 604_800, "slow half-life"
    assert fast_half_life <= slow_half_life, "half-life order"
    assert kappa <= 2 * PRECISION, "kappa"
    # Relative WADs: 1e18 is 100%; accepted cap range is 1 .. 60 bps.
    assert deadband <= 60 * PRECISION // 10_000, "deadband"
    assert max_cap <= 60 * PRECISION // 10_000, "max cap"
    assert min_cap >= PRECISION // 10_000 and min_cap <= max_cap, "min cap"

    POOL = pool
    # A is assumed static. Call refresh_a after any deliberate pool ramp.
    self.POOL_A = staticcall Pool(pool).A()
    FAST_HALF_LIFE = fast_half_life
    SLOW_HALF_LIFE = slow_half_life
    KAPPA = kappa
    DEADBAND = deadband
    MIN_CAP = min_cap
    MAX_CAP = max_cap

    assert pyth != empty(address), "pyth=0"
    assert feed_id > 0 and channel >= 1 and channel <= 4, "feed/channel"
    assert params.base_fee >= 100_000 and params.base_fee <= params.fallback_fee, "base fee"
    assert params.fallback_fee <= FEE_CAP, "fallback fee"
    assert params.capture <= PRECISION, "capture"
    assert 0 < params.max_report_age_ms and params.max_report_age_ms <= 12_000, "report age"
    assert 0 < params.report_expiry_s and params.report_expiry_s <= 604_800, "report expiry"
    PYTH = pyth
    FEED_ID = feed_id
    CHANNEL = channel
    self.parameters = params


@external
@view
def get_fee(xp: uint256[2]) -> uint256:
    params: Parameters = self.parameters
    fallback_fee: uint256 = params.fallback_fee
    previous: State = self.state

    if previous.D == 0:
        return fallback_fee
    # A proportional exit can succeed without its callback. Reject a stale snapshot.
    if staticcall Pool(POOL).D() != previous.D:
        return fallback_fee

    if xp[0] >= previous.xp[0] and xp[1] >= previous.xp[1]:
        return fallback_fee  # Deposit or unchanged quote.
    if xp[0] <= previous.xp[0] and xp[1] <= previous.xp[1]:
        return fallback_fee  # Withdrawal.

    # Opposite balance changes identify a swap. Age comes from the signed observation.
    latest: Report = self.report
    if latest.asset_price == 0:
        return fallback_fee
    report_age_us: uint256 = block.timestamp * 1_000_000 - latest.observation_us
    if report_age_us >= params.report_expiry_s * 1_000_000:
        return fallback_fee
    report_price: uint256 = latest.asset_price
    if previous.price_scale == 0 or previous.xp[0] == 0 or previous.xp[1] == 0:
        return fallback_fee
    coin_in: uint256 = 0 if xp[0] > previous.xp[0] else 1
    coin_out: uint256 = 1 - coin_in

    input_value: uint256 = xp[coin_in] - previous.xp[coin_in]
    output_value: uint256 = previous.xp[coin_out] - xp[coin_out]

    # Value both sides in coin0 at the report, allowing for quote rounding.
    if coin_in == 1:
        if input_value <= 1:
            return fallback_fee
        if input_value - 1 > max_value(uint256) // report_price:
            return fallback_fee
        input_value = (input_value - 1) * report_price // previous.price_scale
    else:
        if output_value == max_value(uint256):
            return fallback_fee
        if output_value + 1 > max_value(uint256) // report_price:
            return fallback_fee
        if (output_value + 1) * report_price > max_value(uint256) - previous.price_scale + 1:
            return fallback_fee
        output_value = (
            (output_value + 1) * report_price + previous.price_scale - 1
        ) // previous.price_scale
    if output_value == 0:
        return fallback_fee

    reported_edge: uint256 = FEE_PRECISION - min(
        FEE_PRECISION, input_value * FEE_PRECISION // output_value
    )
    fee: uint256 = self._discounted_fee(reported_edge, report_age_us)
    if fee >= fallback_fee:
        return fallback_fee

    # The copied math is valid only while the cached deployment-time A is current.
    if staticcall Pool(POOL).future_A_gamma_time() > block.timestamp:
        return fallback_fee
    if self.POOL_A == 0 or staticcall Pool(POOL).A() != self.POOL_A:
        return fallback_fee
    if previous.price_scale == 0:
        return fallback_fee

    p_before: uint256 = self._get_p(previous.xp, previous.D, self.POOL_A)
    p_after: uint256 = self._get_p(xp, previous.D, self.POOL_A)
    if p_before == 0 or p_after == 0:
        return fallback_fee
    if max(p_before, p_after) > max_value(uint256) // previous.price_scale:
        return fallback_fee

    # Convert invariant prices into coin0 per coin1, matching report_price.
    p_before = p_before * previous.price_scale // PRECISION
    p_after = p_after * previous.price_scale // PRECISION
    if p_before == 0 or p_after == 0:
        return fallback_fee

    corrective: bool = False
    if coin_in == 0:
        corrective = p_before < p_after and p_after <= report_price
    else:
        corrective = p_before > p_after and p_after >= report_price
    return fee if corrective else fallback_fee


@external
def refresh_a():
    """@notice Refresh cached A after the pool's amplification ramp changes."""
    self.POOL_A = staticcall Pool(POOL).A()


@external
@view
def get_emas() -> uint256[2]:
    """@return The projected [fast EMA, slow EMA] at the current timestamp."""
    snapshot: State = self.state
    if snapshot.price_scale == 0:
        return [0, 0]
    fast: uint256 = 0
    slow: uint256 = 0
    fast, slow = self._project_emas(
        snapshot, block.timestamp - snapshot.last_update_ts
    )
    return [fast, slow]


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

    current_cap: uint256 = MIN_CAP + (
        (MAX_CAP - MIN_CAP) * ramp_time // CAP_RAMP_SECONDS
    )
    deadband: uint256 = DEADBAND

    fast: uint256 = 0
    slow: uint256 = 0
    fast, slow = self._project_emas(snapshot, elapsed)

    # Extrapolate the slow-to-fast spread by kappa; clamp a negative target to zero.
    raw_target: uint256 = 0
    if fast >= slow:
        raw_target = slow + KAPPA * (fast - slow) // PRECISION
    else:
        step: uint256 = KAPPA * (slow - fast) // PRECISION
        raw_target = slow - min(step, slow)

    ema_gap: uint256 = (
        raw_target - current if raw_target >= current else current - raw_target
    )

    # ema_gap / current <= deadband / PRECISION.
    # Cross-multiply to preserve precision at the inclusive boundary.
    if ema_gap * PRECISION <= current * deadband:
        return current

    max_move: uint256 = current * current_cap // PRECISION
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
        fast, slow = self._project_emas(
            previous, block.timestamp - previous.last_update_ts
        )

    self.state = State(
        last_update_ts=block.timestamp,
        last_prices=last_prices,
        fast_ema=fast,
        slow_ema=slow,
        price_scale=price_scale,
        xp=_xp,
        D=_D,
    )


@internal
@view
def _project_emas(snapshot: State, dt: uint256) -> (uint256, uint256):
    return (
        self._ema(
            snapshot.fast_ema, snapshot.last_prices, snapshot.price_scale, dt, FAST_HALF_LIFE
        ),
        self._ema(
            snapshot.slow_ema, snapshot.last_prices, snapshot.price_scale, dt, SLOW_HALF_LIFE
        ),
    )


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


# ------------------------------- Pyth reports -------------------------------

@external
@view
def verification_fee() -> uint256:
    return staticcall PythLazer(PYTH).verification_fee()


@external
@payable
@nonreentrant
def deliver_oracle_report(report_data: Bytes[112]):
    # Establish the operation boundary before calling the external verifier.
    assert staticcall Pool(POOL).price_scale() > 0, "pool uninitialized"
    asset_price: uint256 = 0
    observation_us: uint256 = 0
    message_us: uint256 = 0
    asset_price, observation_us, message_us = self._verify_report(
        report_data, msg.value
    )

    assert (
        MIN_PRICE <= asset_price and asset_price <= MAX_PRICE
    ), "price bounds"

    # Report delivery must not checkpoint the EMAs or restart the driver cap ramp.
    self.report = Report(
        asset_price=asset_price,
        observation_us=observation_us,
        message_us=message_us,
        delivered_at=block.timestamp,
        delivered_in_block=block.number,
    )
    log ReportAccepted(
        asset_price=asset_price,
        observation_us=observation_us,
        message_us=message_us,
    )


@internal
def _verify_report(
    report_data: Bytes[112], fee_paid: uint256
) -> (uint256, uint256, uint256):
    assert fee_paid == staticcall PythLazer(PYTH).verification_fee(), "verification fee"
    assert len(report_data) == 112, "report length"
    payload: Bytes[41] = b""
    signer: address = empty(address)
    payload, signer = extcall PythLazer(PYTH).verifyUpdate(report_data, value=fee_paid)
    assert signer != empty(address), "signer"

    # Only parse authenticated bytes. Require one feed and the exact property layout.
    assert convert(slice(payload, 0, 4), uint256) == 2479346549, "payload magic"
    assert convert(slice(payload, 12, 1), uint8) == CHANNEL, "channel"
    assert slice(payload, 13, 1) == b"\x01", "one feed"
    assert convert(slice(payload, 14, 4), uint32) == FEED_ID, "feed"
    assert slice(payload, 18, 2) == b"\x03\x00", "price property"
    assert slice(payload, 28, 1) == b"\x04", "exponent property"
    assert slice(payload, 31, 2) == b"\x0c\x01", "observation property"

    # Signed mantissa/exponent encode the asset's USD price.
    mantissa: int64 = convert(convert(slice(payload, 20, 8), bytes8), int64)
    exponent: int16 = convert(convert(slice(payload, 29, 2), bytes2), int16)
    assert mantissa > 0 and -18 <= exponent and exponent <= 0, "price/exponent"
    asset_price: uint256 = (
        convert(mantissa, uint256) * 10**convert(18 + exponent, uint256)
    )

    # Observation age controls admission; message emission alone does not prove freshness.
    message_us: uint256 = convert(slice(payload, 4, 8), uint256)
    observation_us: uint256 = convert(slice(payload, 33, 8), uint256)
    slot_us: uint256 = block.timestamp * 1_000_000
    assert (
        0 < observation_us
        and observation_us <= message_us
        and message_us <= slot_us
    ), "report time"
    assert (
        slot_us - observation_us <= self.parameters.max_report_age_ms * 1_000
    ), "report too old"
    assert observation_us > self.report.observation_us, "observation not newer"
    return asset_price, observation_us, message_us


@internal
@view
def _discounted_fee(reported_edge: uint256, report_age_us: uint256) -> uint256:
    params: Parameters = self.parameters
    expiry_us: uint256 = params.report_expiry_s * 1_000_000
    if report_age_us >= expiry_us:
        return params.fallback_fee

    excess_edge: uint256 = reported_edge - min(reported_edge, params.base_fee)
    fresh_fee: uint256 = min(
        params.fallback_fee, params.base_fee + params.capture * excess_edge // PRECISION
    )
    # Round the age surcharge up in fee units: ceil(delta * sqrt(age / expiry)).
    delta: uint256 = params.fallback_fee - fresh_fee
    numerator: uint256 = delta * delta * report_age_us
    premium: uint256 = isqrt(numerator // expiry_us)
    if premium * premium * expiry_us < numerator:
        premium += 1
    return fresh_fee + premium


@internal
@pure
def _get_p(_xp: uint256[N_COINS], _D: uint256, A: uint256) -> uint256:
    """Return the fee-free marginal price in 1e18 coin0-per-coin1 units."""
    if A == 0 or _D == 0 or _xp[0] == 0 or _xp[1] == 0:
        return 0
    if A > max_value(uint256) // N_COINS:
        return 0
    ANN: uint256 = A * N_COINS
    Dr: uint256 = _D // N_COINS**N_COINS
    for i: uint256 in range(N_COINS):
        if Dr > max_value(uint256) // _D:
            return 0
        Dr = Dr * _D // _xp[i]
    if ANN > max_value(uint256) // _xp[0]:
        return 0
    xp0_A: uint256 = ANN * _xp[0] // A_MULTIPLIER
    if Dr > max_value(uint256) // _xp[0]:
        return 0
    dr_xp0: uint256 = Dr * _xp[0] // _xp[1]
    if xp0_A > max_value(uint256) - dr_xp0:
        return 0
    numerator: uint256 = xp0_A + dr_xp0
    if numerator > max_value(uint256) // PRECISION:
        return 0
    if xp0_A > max_value(uint256) - Dr:
        return 0
    denominator: uint256 = xp0_A + Dr
    if denominator == 0:
        return 0
    return PRECISION * numerator // denominator
