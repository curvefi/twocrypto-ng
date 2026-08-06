import boa
import pytest


PRECISION = 10**18
ACTUATOR_DIVISOR = 5
CAP_RAMP_SECONDS = 3_600
POLICY_DEPLOYER = boa.load_partial("contracts/main/YBTwocryptoPolicy.vy")
POOL_DEPLOYER = boa.load_partial("tests/mocks/YBPolicyPoolMock.vy")


@pytest.fixture
def pool():
    return POOL_DEPLOYER.deploy(100 * PRECISION, 100 * PRECISION)


def _deploy(
    pool,
    fast_half_life=3_600,
    slow_half_life=7_200,
    kappa=2 * PRECISION,
    deadband_bps=0,
    min_cap_bps=1,
    max_cap_bps=60,
    initialize=True,
):
    policy = POLICY_DEPLOYER.deploy(
        pool.address,
        fast_half_life,
        slow_half_life,
        kappa,
        deadband_bps,
        min_cap_bps,
        max_cap_bps,
    )
    if initialize:
        _update(
            policy,
            pool,
            pool.price_scale(),
            pool.last_prices(),
            pool.price_oracle(),
        )
    return policy


def _update(policy, pool, price_scale, last_prices, price_oracle=None):
    if price_oracle is None:
        price_oracle = last_prices
    pool.update_policy(policy, price_scale, price_oracle, last_prices)


def _ema(math_contract, ema, last_prices, dt, half_life):
    alpha = math_contract.wad_exp(-(dt * 693_147_180_559_945_309 // half_life))
    return (last_prices * (PRECISION - alpha) + ema * alpha) // PRECISION


def _allowed_target_gap(current, seconds, min_cap_bps=1, max_cap_bps=60):
    elapsed = min(seconds, CAP_RAMP_SECONDS)
    min_cap = min_cap_bps * PRECISION // 10_000
    max_cap = max_cap_bps * PRECISION // 10_000
    current_cap = min_cap + (max_cap - min_cap) * elapsed // CAP_RAMP_SECONDS
    return current * ACTUATOR_DIVISOR * current_cap // PRECISION


def test_deployment_is_empty_until_first_authenticated_pool_push(pool):
    policy = _deploy(pool, initialize=False)

    assert policy.POOL() == pool.address
    assert policy.FAST_HALF_LIFE() == 3_600
    assert policy.SLOW_HALF_LIFE() == 7_200
    assert policy.KAPPA() == 2 * PRECISION
    assert policy.DEADBAND_BPS() == 0
    assert policy.MIN_CAP_BPS() == 1
    assert policy.MAX_CAP_BPS() == 60
    assert policy.get_fee([PRECISION, PRECISION]) == 0
    assert policy.get_emas() == [0, 0]
    assert policy.get_price_scale() == 0

    state = policy.state()
    assert state.last_update_ts == 0
    assert state.price_scale == 0

    with boa.reverts("auth!"):
        policy.update_pool_state(
            [PRECISION, PRECISION],
            100 * PRECISION,
            100 * PRECISION,
            100 * PRECISION,
            PRECISION,
            PRECISION,
            2 * PRECISION,
            boa.env.evm.patch.timestamp,
        )

    _update(policy, pool, 100 * PRECISION, 110 * PRECISION, 90 * PRECISION)
    state = policy.state()
    assert state.last_update_ts == boa.env.evm.patch.timestamp
    assert state.price_scale == 100 * PRECISION
    assert state.last_prices == 110 * PRECISION
    assert state.fast_ema == 90 * PRECISION
    assert state.slow_ema == 90 * PRECISION


def test_first_pool_push_seeds_both_emas_from_pool_oracle():
    pool = POOL_DEPLOYER.deploy(100 * PRECISION, 90 * PRECISION)
    policy = _deploy(pool, initialize=False)
    _update(policy, pool, 100 * PRECISION, 100 * PRECISION, 90 * PRECISION)
    state = policy.state()

    assert state.last_update_ts == boa.env.evm.patch.timestamp
    assert state.price_scale == 100 * PRECISION
    assert state.last_prices == 100 * PRECISION
    assert state.fast_ema == 90 * PRECISION
    assert state.slow_ema == 90 * PRECISION


def test_first_pool_push_does_not_block_on_zero_values(pool):
    policy = _deploy(pool, initialize=False)

    _update(policy, pool, 0, 0, 0)
    assert policy.get_price_scale() == 0

    _update(policy, pool, 100 * PRECISION, 110 * PRECISION, 90 * PRECISION)
    state = policy.state()
    assert state.price_scale == 100 * PRECISION
    assert state.last_prices == 110 * PRECISION
    assert state.fast_ema == 90 * PRECISION
    assert state.slow_ema == 90 * PRECISION


@pytest.mark.parametrize(
    "last_prices, expected",
    [
        (40 * PRECISION, 50 * PRECISION),
        (120 * PRECISION, 120 * PRECISION),
        (250 * PRECISION, 200 * PRECISION),
    ],
)
def test_last_prices_are_stored_raw_and_capped_only_for_ema(
    pool, math_contract, last_prices, expected
):
    policy = _deploy(pool)
    _update(policy, pool, 100 * PRECISION, last_prices, 100 * PRECISION)

    state = policy.state()
    assert state.last_prices == last_prices
    assert state.fast_ema == 100 * PRECISION
    assert state.slow_ema == 100 * PRECISION

    boa.env.time_travel(seconds=7_200)
    _update(policy, pool, 100 * PRECISION, 100 * PRECISION, 999 * PRECISION)
    assert policy.state().fast_ema == _ema(math_contract, 100 * PRECISION, expected, 7_200, 3_600)
    assert policy.state().slow_ema == _ema(math_contract, 100 * PRECISION, expected, 7_200, 7_200)


def test_view_projection_matches_same_timestamp_state_commit(pool, math_contract):
    policy = _deploy(pool)
    current = 110 * PRECISION
    _update(policy, pool, current, 100 * PRECISION, 100 * PRECISION)

    boa.env.time_travel(seconds=1_000)
    _update(policy, pool, current, 120 * PRECISION, 100 * PRECISION)
    assert policy.state().last_prices == 120 * PRECISION

    boa.env.time_travel(seconds=3_600)
    fast = _ema(math_contract, 100 * PRECISION, 120 * PRECISION, 3_600, 3_600)
    slow = _ema(math_contract, 100 * PRECISION, 120 * PRECISION, 3_600, 7_200)
    expected_target = slow + 2 * (fast - slow)
    expected_target = min(expected_target, current * 10_300 // 10_000)
    assert policy.get_emas() == [fast, slow]
    target_before = policy.get_price_scale()

    assert target_before == expected_target

    _update(policy, pool, current, 130 * PRECISION, 999 * PRECISION)
    updated = policy.state()
    assert updated.fast_ema == fast
    assert updated.slow_ema == slow
    assert updated.last_prices == 130 * PRECISION
    assert updated.last_update_ts == boa.env.evm.patch.timestamp
    assert policy.get_emas() == [fast, slow]
    assert policy.get_price_scale() == current + _allowed_target_gap(current, 0)


def test_bearish_underflow_fallback_is_staleness_capped(math_contract):
    pool = POOL_DEPLOYER.deploy(100 * PRECISION, 200 * PRECISION)
    policy = _deploy(
        pool,
        fast_half_life=600,
        slow_half_life=604_800,
        kappa=15 * PRECISION // 10,
    )
    _update(policy, pool, 100 * PRECISION, 50 * PRECISION)
    boa.env.time_travel(seconds=6_000)

    fast = _ema(math_contract, 200 * PRECISION, 50 * PRECISION, 6_000, 600)
    slow = _ema(math_contract, 200 * PRECISION, 50 * PRECISION, 6_000, 604_800)
    assert 15 * (slow - fast) // 10 >= slow
    assert policy.get_price_scale() == 97 * PRECISION


def test_same_block_latest_last_prices_win_without_advancing_slow_ema(pool):
    policy = _deploy(pool)
    _update(policy, pool, 100 * PRECISION, 100 * PRECISION)
    _update(policy, pool, 100 * PRECISION, 120 * PRECISION, 100 * PRECISION)
    _update(policy, pool, 100 * PRECISION, 130 * PRECISION, 100 * PRECISION)

    state = policy.state()
    assert state.fast_ema == 100 * PRECISION
    assert state.slow_ema == 100 * PRECISION
    assert state.last_prices == 130 * PRECISION


def test_emas_naturally_converge_after_wad_exp_cutoff(pool):
    policy = _deploy(pool)
    _update(policy, pool, 100 * PRECISION, 200 * PRECISION)
    boa.env.time_travel(seconds=61 * 7_200)

    assert policy.get_emas() == [200 * PRECISION, 200 * PRECISION]


@pytest.mark.parametrize("seconds", [0, 1, 12, 59, 60, 72, 3_599, 3_600, 7_200])
@pytest.mark.parametrize("last_prices, direction", [(200, 1), (50, -1)])
def test_cap_ramps_with_fractional_bps_precision(pool, seconds, last_prices, direction):
    policy = _deploy(pool, initialize=False)
    current = 100 * PRECISION
    observation = last_prices * PRECISION
    _update(policy, pool, current, observation, observation)
    boa.env.time_travel(seconds=seconds)

    expected = current + direction * _allowed_target_gap(current, seconds)
    assert policy.get_price_scale() == expected


@pytest.mark.parametrize(
    "seconds",
    [0, 1, 12, 59, 60, 299, 300, 360, 3_599, 3_600],
)
def test_cap_interpolates_between_nonzero_endpoints(pool, seconds):
    policy = _deploy(pool, min_cap_bps=5, max_cap_bps=60, initialize=False)
    current = 100 * PRECISION
    _update(policy, pool, current, 200 * PRECISION, 200 * PRECISION)
    boa.env.time_travel(seconds=seconds)

    expected = current + _allowed_target_gap(current, seconds, 5, 60)
    assert policy.get_price_scale() == expected


def test_authenticated_update_resets_staleness_cap(pool):
    policy = _deploy(pool, initialize=False)
    current = 100 * PRECISION
    _update(policy, pool, current, 200 * PRECISION, 200 * PRECISION)
    boa.env.time_travel(seconds=600)
    assert policy.get_price_scale() == current + _allowed_target_gap(current, 600)

    touched_at = boa.env.evm.patch.timestamp
    _update(policy, pool, current, 200 * PRECISION)

    assert policy.state().last_update_ts == touched_at
    assert policy.get_price_scale() == current + _allowed_target_gap(current, 0)


@pytest.mark.parametrize("direction", [-1, 1])
def test_deadband_is_exact_in_native_move_units(pool, direction):
    policy = _deploy(
        pool,
        kappa=PRECISION,
        deadband_bps=10,
        min_cap_bps=60,
        max_cap_bps=60,
        initialize=False,
    )
    current = 100 * PRECISION
    # A 50 bps policy gap requests a 10 bps native move: inclusive deadband.
    boundary = current + direction * current * 50 // 10_000
    _update(policy, pool, current, boundary, boundary)
    assert policy.get_price_scale() == current

    # 50.9 bps requests 10.18 bps and must not be hidden by integer-bps flooring.
    policy = _deploy(
        pool,
        kappa=PRECISION,
        deadband_bps=10,
        min_cap_bps=60,
        max_cap_bps=60,
        initialize=False,
    )
    beyond = current + direction * current * 509 // 100_000
    _update(policy, pool, current, beyond, beyond)
    assert policy.get_price_scale() == beyond


def test_deadband_checks_raw_signal_before_cap(pool):
    policy = _deploy(pool, kappa=PRECISION, deadband_bps=10, initialize=False)
    current = 100 * PRECISION
    raw_target = current * 10_060 // 10_000  # 60 bps gap => 12 bps native request
    _update(policy, pool, current, raw_target, raw_target)

    # The 12 bps raw signal clears the 10 bps deadband, then the fresh 1 bps
    # cap limits the returned target to a 5 bps gap.
    assert policy.get_price_scale() == current + _allowed_target_gap(current, 0)


def test_deadband_and_cap_are_relative_to_current_scale(pool):
    current = 69 * PRECISION
    policy = _deploy(pool, kappa=PRECISION, deadband_bps=10, initialize=False)

    # A 10 bps native deadband corresponds to a 50 bps target gap: 0.345 at 69.
    boundary = current + current * ACTUATOR_DIVISOR * 10 // 10_000
    _update(policy, pool, current, boundary, boundary)
    assert policy.get_price_scale() == current

    policy = _deploy(pool, kappa=PRECISION, deadband_bps=10, initialize=False)
    raw_target = current + PRECISION // 2  # 0.5 / 69 / 5 = 14.49 bps native
    _update(policy, pool, current, raw_target, raw_target)

    assert policy.get_price_scale() == current + _allowed_target_gap(current, 0)


@pytest.mark.parametrize(
    "xp",
    [
        [0, 0],
        [PRECISION, PRECISION],
        [3 * PRECISION, PRECISION],
        [100 * PRECISION, PRECISION],
        [PRECISION, 250 * PRECISION],
    ],
)
def test_get_fee_always_returns_native_fallback(pool, xp):
    policy = _deploy(pool)

    assert policy.get_fee(xp) == 0
    boa.env.time_travel(seconds=604_800)
    assert policy.get_fee(xp) == 0

    _update(policy, pool, 100 * PRECISION, 120 * PRECISION)
    assert policy.get_fee(xp) == 0


@pytest.mark.parametrize(
    "kwargs, reason",
    [
        ({"fast_half_life": 599}, "fast half-life"),
        ({"slow_half_life": 599}, "slow half-life"),
        ({"fast_half_life": 7_201}, "half-life order"),
        ({"kappa": 2 * PRECISION + 1}, "kappa"),
        ({"deadband_bps": 61}, "deadband"),
        ({"max_cap_bps": 61}, "max cap"),
        ({"min_cap_bps": 0}, "min cap"),
        ({"min_cap_bps": 61}, "min cap"),
    ],
)
def test_constructor_rejects_out_of_range_parameters(pool, kwargs, reason):
    with boa.reverts(reason):
        _deploy(pool, **kwargs)


def test_equal_half_lives_are_allowed(pool):
    policy = _deploy(pool, fast_half_life=7_200, slow_half_life=7_200)

    assert policy.FAST_HALF_LIFE() == policy.SLOW_HALF_LIFE()
