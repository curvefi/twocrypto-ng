import boa
import pytest


PRECISION = 10**18
MID_FEE = 3_000_000  # 3 bps at Twocrypto's 1e10 fee precision
OUT_FEE = 30_000_000  # 30 bps
FEE_GAMMA = 23 * 10**16
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
    min_cap_bps=0,
    max_cap_bps=60,
    cap_ramp_seconds=3_600,
    mid_fee=MID_FEE,
    out_fee=OUT_FEE,
    fee_gamma=FEE_GAMMA,
    min_dynamic_fee=10**6,  # 1 bps in 1e10 fee precision
    calm_seconds=3_600,
    fee_ramp_seconds=3_600,
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
        cap_ramp_seconds,
        mid_fee,
        out_fee,
        fee_gamma,
        min_dynamic_fee,
        calm_seconds,
        fee_ramp_seconds,
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


def _skew_fee(xp, mid_fee=MID_FEE, out_fee=OUT_FEE, fee_gamma=FEE_GAMMA):
    B = xp[0] + xp[1]
    B = PRECISION * 4 * xp[0] // B * xp[1] // B
    B = fee_gamma * B // (fee_gamma * B // PRECISION + PRECISION - B)
    return (mid_fee * B + out_fee * (PRECISION - B)) // PRECISION


def test_deployment_is_empty_until_first_authenticated_pool_push(pool):
    policy = _deploy(pool, initialize=False)

    assert policy.POOL() == pool.address
    assert policy.FAST_HALF_LIFE() == 3_600
    assert policy.SLOW_HALF_LIFE() == 7_200
    assert policy.KAPPA() == 2 * PRECISION
    assert policy.DEADBAND_BPS() == 0
    assert policy.MIN_CAP_BPS() == 0
    assert policy.MAX_CAP_BPS() == 60
    assert policy.MID_FEE() == MID_FEE
    assert policy.OUT_FEE() == OUT_FEE
    assert policy.FEE_GAMMA() == FEE_GAMMA
    assert policy.CAP_RAMP_SECONDS() == 3_600
    assert policy.MIN_DYNAMIC_FEE() == 10**6
    assert policy.CALM_SECONDS() == 3_600
    assert policy.FEE_RAMP_SECONDS() == 3_600
    assert policy.get_fee([PRECISION, PRECISION]) == 0
    assert policy.get_emas() == [0, 0]
    assert policy.get_price_scale() == 0

    state = policy.state()
    assert state.last_update_ts == 0
    assert state.pool_price_scale == 0

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
    assert state.pool_price_scale == 100 * PRECISION
    assert state.last_prices == 110 * PRECISION
    assert state.fast_ema == 90 * PRECISION
    assert state.slow_ema == 90 * PRECISION


def test_first_pool_push_seeds_both_emas_from_pool_oracle():
    pool = POOL_DEPLOYER.deploy(100 * PRECISION, 90 * PRECISION)
    policy = _deploy(pool, initialize=False)
    _update(policy, pool, 100 * PRECISION, 100 * PRECISION, 90 * PRECISION)
    state = policy.state()

    assert state.last_update_ts == boa.env.evm.patch.timestamp
    assert state.pool_price_scale == 100 * PRECISION
    assert state.last_prices == 100 * PRECISION
    assert state.fast_ema == 90 * PRECISION
    assert state.slow_ema == 90 * PRECISION


def test_first_pool_push_does_not_block_on_zero_values(pool):
    policy = _deploy(pool, initialize=False)

    _update(policy, pool, 0, 0, 0)
    assert policy.get_price_scale() == 0

    _update(policy, pool, 100 * PRECISION, 110 * PRECISION, 90 * PRECISION)
    state = policy.state()
    assert state.pool_price_scale == 100 * PRECISION
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
    assert policy.get_price_scale() == current


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


@pytest.mark.parametrize(
    "seconds, cap_bps",
    [(0, 0), (59, 0), (60, 1), (65, 1), (77, 1), (3_599, 59), (3_600, 60), (7_200, 60)],
)
@pytest.mark.parametrize("last_prices, direction", [(200, 1), (50, -1)])
def test_staleness_cap_bounds_native_actuator_step(pool, seconds, cap_bps, last_prices, direction):
    policy = _deploy(pool)
    _update(policy, pool, 100 * PRECISION, last_prices * PRECISION)
    boa.env.time_travel(seconds=seconds)

    expected = 100 * PRECISION + direction * 100 * PRECISION * 5 * cap_bps // 10_000
    assert policy.get_price_scale() == expected


@pytest.mark.parametrize(
    "seconds, cap_bps",
    [(0, 5), (59, 5), (60, 5), (299, 9), (300, 9), (360, 10), (3_599, 59), (3_600, 60)],
)
def test_staleness_cap_interpolates_from_min_to_max_over_sixty_minutes(pool, seconds, cap_bps):
    policy = _deploy(pool, min_cap_bps=5, max_cap_bps=60)
    _update(policy, pool, 100 * PRECISION, 200 * PRECISION)
    boa.env.time_travel(seconds=3_600)
    _update(policy, pool, 100 * PRECISION, 200 * PRECISION)
    boa.env.time_travel(seconds=seconds)

    expected = 100 * PRECISION + 100 * PRECISION * 5 * cap_bps // 10_000
    assert policy.get_price_scale() == expected


def test_cap_ramp_duration_is_configurable(pool):
    policy = _deploy(pool, cap_ramp_seconds=7_200)
    _update(policy, pool, 100 * PRECISION, 200 * PRECISION)
    boa.env.time_travel(seconds=3_600)

    # halfway through the doubled ramp: cap = 60 * 3_600 // 7_200 = 30 bps
    assert policy.get_price_scale() == 100 * PRECISION + 100 * PRECISION * 5 * 30 // 10_000


def test_authenticated_update_resets_staleness_cap(pool):
    policy = _deploy(pool)
    _update(policy, pool, 100 * PRECISION, 200 * PRECISION)
    boa.env.time_travel(seconds=600)
    assert policy.get_price_scale() == 1005 * PRECISION // 10

    touched_at = boa.env.evm.patch.timestamp
    _update(policy, pool, 100 * PRECISION, 200 * PRECISION)

    assert policy.state().last_update_ts == touched_at
    assert policy.get_price_scale() == 100 * PRECISION


def test_deadband_returns_nonzero_hold_target(pool):
    policy = _deploy(pool, deadband_bps=60)
    current = 100 * PRECISION
    _update(policy, pool, current, current * 10_050 // 10_000)
    boa.env.time_travel(seconds=7_200)

    assert policy.get_price_scale() == current


@pytest.mark.parametrize(
    "xp",
    [
        [PRECISION, PRECISION],
        [3 * PRECISION, PRECISION],
        [100 * PRECISION, PRECISION],
        [PRECISION, 250 * PRECISION],
    ],
)
def test_get_fee_prices_policy_skew_fee_after_init(pool, xp):
    policy = _deploy(pool)

    assert policy.get_fee(xp) == _skew_fee(xp)
    assert MID_FEE <= policy.get_fee(xp) <= OUT_FEE
    # balanced pool prices at exactly mid fee
    assert policy.get_fee([PRECISION, PRECISION]) == MID_FEE


@pytest.mark.parametrize(
    "seconds, progress_bps",
    [
        (0, 0),
        (3_599, 0),
        (3_600, 0),  # grace boundary: decay not started
        (3_601, 2),  # first decayed second: 10_000 * 1 // 3_600
        (3_660, 166),  # one minute into decay: 10_000 * 60 // 3_600
        (5_400, 5_000),  # halfway through the decay window
        (7_199, 9_997),  # 10_000 * 3_599 // 3_600
        (7_200, 10_000),  # floor reached at grace + decay
        (1_000_000, 10_000),
    ],
)
def test_fee_decays_from_skew_to_floor_after_grace(pool, seconds, progress_bps):
    policy = _deploy(pool)
    boa.env.time_travel(seconds=seconds)

    xp = [3 * PRECISION, PRECISION]
    floor = 10**6  # the default min_dynamic_fee
    skew = _skew_fee(xp)
    assert policy.get_fee(xp) == skew - (skew - floor) * progress_bps // 10_000


def test_pool_touch_resets_fee_decay(pool):
    policy = _deploy(pool)
    boa.env.time_travel(seconds=10_000)
    xp = [3 * PRECISION, PRECISION]
    assert policy.get_fee(xp) == 10**6  # fully decayed to the 1 bps floor

    _update(policy, pool, 100 * PRECISION, 100 * PRECISION)
    assert policy.get_fee(xp) == _skew_fee(xp)


def test_decay_lands_exactly_on_min_fee_floor(pool):
    policy = _deploy(pool, min_dynamic_fee=2 * 10**6)
    xp = [3 * PRECISION, PRECISION]
    assert policy.get_fee(xp) == _skew_fee(xp)  # floor inactive at full fee

    boa.env.time_travel(seconds=1_000_000)
    assert policy.get_fee(xp) == 2 * 10**6  # 2 bps at 1e10 fee precision


def test_decayed_fee_never_reaches_the_native_fee_sentinel(pool):
    # the lowest legal floor is the pool's own MIN_FEE (0.1 bps)
    policy = _deploy(pool, min_dynamic_fee=10**5)
    boa.env.time_travel(seconds=1_000_000)

    assert policy.get_fee([3 * PRECISION, PRECISION]) == 10**5


@pytest.mark.parametrize(
    "kwargs, reason",
    [
        ({"fast_half_life": 599}, "fast half-life"),
        ({"slow_half_life": 599}, "slow half-life"),
        ({"kappa": 2 * PRECISION + 1}, "kappa"),
        ({"deadband_bps": 61}, "deadband"),
        ({"max_cap_bps": 61}, "max cap"),
        ({"min_cap_bps": 61}, "min cap"),
        ({"mid_fee": 10**5 - 1}, "mid fee"),
        ({"out_fee": MID_FEE - 1}, "out fee"),
        ({"out_fee": 10**10 + 1}, "out fee"),
        ({"fee_gamma": 0}, "fee gamma"),
        ({"fee_gamma": PRECISION + 1}, "fee gamma"),
        ({"min_dynamic_fee": 4 * 10**6}, "min fee"),  # 4 bps floor above the 3 bps mid fee
        ({"min_dynamic_fee": 10**5 - 1}, "min fee"),  # floor below the pool's MIN_FEE
        ({"cap_ramp_seconds": 59}, "cap ramp"),
        ({"cap_ramp_seconds": 604_801}, "cap ramp"),
        ({"calm_seconds": 604_801}, "calm"),
        ({"fee_ramp_seconds": 59}, "fee ramp"),
        ({"fee_ramp_seconds": 604_801}, "fee ramp"),
    ],
)
def test_constructor_rejects_out_of_range_parameters(pool, kwargs, reason):
    with boa.reverts(reason):
        _deploy(pool, **kwargs)
