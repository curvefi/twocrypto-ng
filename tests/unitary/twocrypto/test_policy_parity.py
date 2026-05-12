import boa

from tests.conftest import _deploy_pool
from tests.utils.constants import POOL_DEPLOYER
from tests.utils.god_mode import GodModePool

INITIAL_LIQUIDITY = 10_000_000 * 10**18
TRADE_VALUE = INITIAL_LIQUIDITY // 20
NUM_SWAPS = 10
ZERO_STUB_POLICY_DEPLOYER = boa.load_partial("tests/mocks/ZeroStubPolicy.vy")


def _state_snapshot(pool):
    return {
        "balances": pool.balances(),
        "D": pool.D(),
        "total_supply": pool.totalSupply(),
        "price_scale": pool.price_scale(),
        "price_oracle": pool.price_oracle(),
        "last_prices": pool.last_prices(),
        "virtual_price": pool.virtual_price(),
        "xcp_profit": pool.xcp_profit(),
        "admin_balances": [pool.admin_balances(i) for i in range(2)],
    }


def _assert_matching_state(legacy_pool, hooked_pool):
    assert _state_snapshot(legacy_pool) == _state_snapshot(hooked_pool)


def _pool_ratio(pool):
    balance_0 = pool.balances(0)
    balance_1 = pool.balances(1)
    value_1 = balance_1 * pool.price_scale() // 10**18
    return balance_0 / value_1


def _balance_both(legacy_pool, hooked_pool, precision=0.0001):
    ratio = _pool_ratio(legacy_pool)
    _assert_matching_state(legacy_pool, hooked_pool)

    iterations = 0
    while abs(ratio - 1) > precision:
        iterations += 1
        larger_coin = 0 if ratio > 1 else 1
        smaller_coin = 1 - larger_coin
        trade_back_size = int(legacy_pool.balances(smaller_coin) * (abs(ratio - 1) / 2))
        legacy_pool.exchange(smaller_coin, trade_back_size, update_ema=False)
        hooked_pool.exchange(smaller_coin, trade_back_size, update_ema=False)
        _assert_matching_state(legacy_pool, hooked_pool)
        ratio = _pool_ratio(legacy_pool)
        if iterations > 100:
            raise AssertionError(f"failed to balance pool: {ratio}")


def _move_price_oracle_both(legacy_pool, hooked_pool, price_change):
    current_price = legacy_pool.price_oracle()
    assert current_price == hooked_pool.price_oracle()

    goal_price = current_price * (1 + price_change)
    price_diff_pre = goal_price - current_price
    main_direction = 0 if price_diff_pre > 0 else 1
    price_diff_post = price_diff_pre

    iterations = 0
    while price_diff_pre * price_diff_post > 0:
        trade_size = int(legacy_pool.balances(main_direction) * abs(price_change)) // 20
        boa.env.time_travel(seconds=7 * 86400)
        legacy_pool.exchange(main_direction, trade_size, update_ema=False)
        hooked_pool.exchange(main_direction, trade_size, update_ema=False)
        _assert_matching_state(legacy_pool, hooked_pool)
        price_diff_pre = price_diff_post
        price_diff_post = goal_price - legacy_pool.price_oracle()
        iterations += 1
        if iterations > 100:
            raise AssertionError(f"failed to move price: {price_diff_post}")


def _move_price_scale_both(legacy_pool, hooked_pool, price_change):
    _move_price_oracle_both(legacy_pool, hooked_pool, price_change)
    _balance_both(legacy_pool, hooked_pool)

    for _ in range(NUM_SWAPS):
        boa.env.time_travel(seconds=7 * 86400)
        legacy_pool.exchange(0, 10**18, update_ema=False)
        hooked_pool.exchange(0, 10**18, update_ema=False)
        _assert_matching_state(legacy_pool, hooked_pool)

        boa.env.time_travel(seconds=7 * 86400)
        legacy_pool.exchange(1, 10**18, update_ema=False)
        hooked_pool.exchange(1, 10**18, update_ema=False)
        _assert_matching_state(legacy_pool, hooked_pool)

    _balance_both(legacy_pool, hooked_pool)


def _fresh_pool(factory, factory_admin, coins, params, deployer, math_contract, views_contract):
    return GodModePool(POOL_DEPLOYER.at(_deploy_pool(factory, params, coins, deployer)))


def test_compare_fee_parity(pool, pool_with_policy_contract):
    legacy_pool = GodModePool(pool)
    hooked_pool = GodModePool(pool_with_policy_contract)

    assert legacy_pool.POLICY() == "0x0000000000000000000000000000000000000000"
    assert hooked_pool.POLICY() != "0x0000000000000000000000000000000000000000"

    legacy_pool.add_liquidity_balanced(INITIAL_LIQUIDITY)
    hooked_pool.add_liquidity_balanced(INITIAL_LIQUIDITY)

    trade_sizes = legacy_pool.compute_balanced_amounts(TRADE_VALUE)

    assert _state_snapshot(legacy_pool) == _state_snapshot(hooked_pool)

    for step in range(NUM_SWAPS):
        i = step % 2
        j = 1 - i
        dx = trade_sizes[i]

        legacy_dy_view = legacy_pool.get_dy(i, j, dx)
        hooked_dy_view = hooked_pool.get_dy(i, j, dx)
        assert legacy_dy_view == hooked_dy_view

        legacy_dy = legacy_pool.exchange(i, dx)
        hooked_dy = hooked_pool.exchange(i, dx)
        assert legacy_dy == hooked_dy

        assert _state_snapshot(legacy_pool) == _state_snapshot(hooked_pool)


def test_compare_price_scale_parity(pool, pool_with_policy_contract):
    legacy_pool = GodModePool(pool)
    hooked_pool = GodModePool(pool_with_policy_contract)

    legacy_pool.add_liquidity_balanced(INITIAL_LIQUIDITY)
    hooked_pool.add_liquidity_balanced(INITIAL_LIQUIDITY)

    initial_price_scale = legacy_pool.price_scale()
    _assert_matching_state(legacy_pool, hooked_pool)

    _move_price_scale_both(legacy_pool, hooked_pool, 0.3)

    _assert_matching_state(legacy_pool, hooked_pool)
    assert legacy_pool.price_scale() != initial_price_scale

    price_change_back = initial_price_scale / legacy_pool.price_scale() - 1
    _move_price_scale_both(legacy_pool, hooked_pool, 0.95 * price_change_back)

    _assert_matching_state(legacy_pool, hooked_pool)


def test_compare_zero_stub_policy_parity(
    factory,
    factory_admin,
    coins,
    params,
    deployer,
    math_contract,
    views_contract,
):
    with boa.env.anchor():
        legacy_pool = _fresh_pool(
            factory, factory_admin, coins, params, deployer, math_contract, views_contract
        )
        hooked_pool = _fresh_pool(
            factory, factory_admin, coins, params, deployer, math_contract, views_contract
        )

        zero_policy = ZERO_STUB_POLICY_DEPLOYER.deploy()
        hooked_pool.set_policy_contract(zero_policy, sender=factory_admin)

        legacy_pool.add_liquidity_balanced(INITIAL_LIQUIDITY)
        hooked_pool.add_liquidity_balanced(INITIAL_LIQUIDITY)

        assert _state_snapshot(legacy_pool) == _state_snapshot(hooked_pool)

        trade_sizes = legacy_pool.compute_balanced_amounts(TRADE_VALUE)
        for step in range(NUM_SWAPS):
            i = step % 2
            j = 1 - i
            dx = trade_sizes[i]

            legacy_dy_view = legacy_pool.get_dy(i, j, dx)
            hooked_dy_view = hooked_pool.get_dy(i, j, dx)
            assert legacy_dy_view == hooked_dy_view

            legacy_dy = legacy_pool.exchange(i, dx)
            hooked_dy = hooked_pool.exchange(i, dx)
            assert legacy_dy == hooked_dy

            assert _state_snapshot(legacy_pool) == _state_snapshot(hooked_pool)

        initial_price_scale = legacy_pool.price_scale()
        _move_price_scale_both(legacy_pool, hooked_pool, 0.3)
        _assert_matching_state(legacy_pool, hooked_pool)
        assert legacy_pool.price_scale() != initial_price_scale
