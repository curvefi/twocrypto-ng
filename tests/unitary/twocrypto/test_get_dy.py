from tests.utils.god_mode import GodModePool
from tests.utils.constants import N_COINS
import pytest


@pytest.mark.parametrize("i", range(N_COINS))
@pytest.mark.parametrize("dx_ratio", range(1, 10))
def test_default_behavior(pool, i, dx_ratio):
    pool: GodModePool = GodModePool(pool)
    init_liq = 10_000_000 * 10**18
    # Add balanced liquidity
    pool.add_liquidity_balanced(init_liq)

    dx = init_liq // dx_ratio
    dy_view = pool.get_dy(i, 1 - i, dx)
    # Perform exchange to unbalance the pool
    dy_true = pool.exchange(i, dx)
    print("true", dy_true)
    print("view", dy_view)
    assert dy_true == dy_view
