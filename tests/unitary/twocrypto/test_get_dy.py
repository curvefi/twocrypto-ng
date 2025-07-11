from tests.utils.god_mode import GodModePool
from tests.utils.constants import N_COINS
import pytest

# @external
# @view
# def get_dy(i: uint256, j: uint256, dx: uint256) -> uint256:
#     """
#     @notice Get amount of coin[j] tokens received for swapping in dx amount of coin[i]
#     @dev Includes fee.
#     @param i index of input token. Check pool.coins(i) to get coin address at ith index
#     @param j index of output token
#     @param dx amount of input coin[i] tokens
#     @return uint256 Exact amount of output j tokens for dx amount of i input tokens.
#     """
#     return staticcall self.view_contract.get_dy(i, j, dx, self)


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
