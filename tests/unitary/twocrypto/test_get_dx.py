from tests.utils.god_mode import GodModePool
from tests.utils.constants import N_COINS
import pytest
import boa


@pytest.mark.parametrize("i", range(N_COINS))
@pytest.mark.parametrize("dx_ratio", range(2, 10))
# @pytest.mark.parametrize("dx_ratio", [2])
def test_improves_with_n(pool, i, dx_ratio):
    pool: GodModePool = GodModePool(pool)
    init_liq = 10_000_000 * 10**18
    pool.add_liquidity_balanced(init_liq)
    ratio_prev = 0
    for n_iter in range(1, 10, 2):
        with boa.env.anchor():
            dy_desired = pool.balances()[1 - i] // dx_ratio
            dx_view = pool.get_dx(i, 1 - i, dy_desired, n_iter)
            dy_true = pool.exchange(i, dx_view)
            # this ratio is always < 1 (we divide by the larger value)
            ratio_new = min(dy_true, dy_desired) / max(dy_true, dy_desired)
            assert ratio_new >= ratio_prev
            ratio_prev = ratio_new
            print("ratio", ratio_new)
