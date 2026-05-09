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


def test_first_deposit_behavior(pool):
    gm_pool = GodModePool(pool)
    amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY)

    expected_lp = pool.calc_token_amount(amounts, True)
    resulted_lp = gm_pool.add_liquidity(amounts, 0)

    assert resulted_lp == expected_lp


def test_viewer_withdraw_quote_adds_fee(pool, views_contract):
    gm_pool = GodModePool(pool)
    seed_amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY)
    gm_pool.add_liquidity(seed_amounts, 0)

    deposit_amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY // 10)
    deposit_quote = views_contract.calc_token_amount(deposit_amounts, True, pool.address)
    assert gm_pool.add_liquidity(deposit_amounts, 0) == deposit_quote

    withdraw_amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY // 100)

    no_fee_burn, _, xp = views_contract.internal._calc_dtoken_nofee(
        withdraw_amounts, False, pool.address
    )
    fee = pool.calc_token_fee(withdraw_amounts, xp, False, False)
    burn_quote = views_contract.calc_token_amount(withdraw_amounts, False, pool.address)

    assert burn_quote == no_fee_burn + fee * no_fee_burn // 10**10 + 1
