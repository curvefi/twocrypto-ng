from tests.utils.god_mode import GodModePool
import pytest


INITIAL_LIQUIDITY = 10_000_000 * 10**18


@pytest.mark.parametrize("amounts_ratio", range(1, 10))
def test_default_behavior(pool, amounts_ratio):
    gm_pool = GodModePool(pool)
    amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY)
    gm_pool.add_liquidity(amounts, 0)  # seed pool

    amounts_add = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY // amounts_ratio)
    expected_lp = pool.calc_token_amount(amounts_add, True)
    resulted_lp = gm_pool.add_liquidity(amounts_add, 0)

    assert resulted_lp == expected_lp
