from tests.utils.god_mode import GodModePool

INITIAL_LIQUIDITY = 10_000_000 * 10**18
TRADE_VALUE = INITIAL_LIQUIDITY // 20
NUM_SWAPS = 10


def _state_snapshot(pool):
    return {
        "balances": pool.balances(),
        "D": pool.D(),
        "total_supply": pool.totalSupply(),
        "price_scale": pool.price_scale(),
        "virtual_price": pool.virtual_price(),
        "xcp_profit": pool.xcp_profit(),
        "xcp_profit_a": pool.xcp_profit_a(),
    }


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
