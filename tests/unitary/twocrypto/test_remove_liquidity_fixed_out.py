from tests.utils.constants import N_COINS
import pytest
from pytest import fixture
import boa


@fixture(scope="module")
def gm_pool(gm_pool):
    # We seed the pool with 200 dollars worth of liquidity
    gm_pool.add_liquidity_balanced(100 * 10**18)
    return gm_pool


@pytest.mark.parametrize("i", range(N_COINS))
@pytest.mark.parametrize("amount_i_percent", [0.25, 0.5, 0.75])
@pytest.mark.parametrize("lp_token_percent", [0.5, 0.75])
def test_withdraw_fixed_out(i, amount_i_percent, lp_token_percent, gm_pool):
    j = 1 - i

    lp_tokens = gm_pool.balanceOf(boa.env.eoa)

    # 75% of the lp tokens because 100% would leave the pool with 0 liquidity
    amount_to_withdraw = int(lp_tokens * lp_token_percent)

    t0 = gm_pool.balances_snapshot()

    # Calculate how much of coin i we want to withdraw (50% of pool's balance)
    amount_i = int(t0["pool_coins"][i] * amount_i_percent)

    expected_dy = gm_pool.calc_withdraw_fixed_out(amount_to_withdraw, i, amount_i)

    # Execute the withdrawal
    actual_dy = gm_pool.remove_liquidity_fixed_out(amount_to_withdraw, i, amount_i, 0)

    t1 = gm_pool.balances_snapshot()

    # Check LP token balances
    assert (
        t1["lp_supply"] == t0["lp_supply"] - amount_to_withdraw
    ), "pool lp balance did not decrease after removing liquidity"
    assert (
        t1["user_lp"] == t0["user_lp"] - amount_to_withdraw
    ), "user lp balance did not decrease after removing liquidity"

    # Check coin balances for user
    assert (
        t1["user_coins"][i] == t0["user_coins"][i] + amount_i
    ), "user i coin balance did not increase by the specified amount"
    assert (
        t1["user_coins"][j] == t0["user_coins"][j] + expected_dy
    ), "user j coin balance did not increase by the expected amount"

    # Check coin balances for pool
    assert (
        t1["pool_coins"][i] == t0["pool_coins"][i] - amount_i
    ), "pool i coin balance did not decrease by the specified amount"
    assert (
        t1["pool_coins"][j] == t0["pool_coins"][j] - expected_dy
    ), "pool j coin balance did not decrease by the expected amount"

    # Check that the calculated and actual amounts match
    assert actual_dy == expected_dy, "actual and expected amounts of coin j do not match"


@pytest.mark.parametrize("i", range(N_COINS))
@pytest.mark.parametrize("amount_i_percent", [0.25, 0.5, 0.75])
@pytest.mark.parametrize("lp_token_percent", [0.5, 0.75])
def test_slippage_protection(i, amount_i_percent, lp_token_percent, gm_pool):
    lp_tokens = gm_pool.balanceOf(boa.env.eoa)
    amount_to_withdraw = int(lp_tokens * lp_token_percent)

    t0 = gm_pool.balances_snapshot()
    amount_i = int(t0["pool_coins"][i] * amount_i_percent)

    with boa.env.anchor():
        expected_dy = gm_pool.calc_withdraw_fixed_out(amount_to_withdraw, i, amount_i)

        # Should revert when min_amount_j is higher than what will be received
        with boa.reverts("slippage"):
            gm_pool.remove_liquidity_fixed_out(amount_to_withdraw, i, amount_i, expected_dy + 1)
            # This should not revert
            gm_pool.remove_liquidity_fixed_out(amount_to_withdraw, i, amount_i, expected_dy)

        # Should succeed when min_amount_j is exactly what will be received
        gm_pool.remove_liquidity_fixed_out(amount_to_withdraw, i, amount_i, expected_dy)


@pytest.mark.parametrize("i", range(N_COINS))
@pytest.mark.parametrize("lp_token_percent", [0.5, 0.75])
def test_zero_amount_i(i, lp_token_percent, gm_pool):
    """Test that setting amount_i to 0 is equivalent to remove_liquidity_one_coin for the other token"""
    j = 1 - i

    lp_tokens = gm_pool.balanceOf(boa.env.eoa)
    amount_to_withdraw = int(lp_tokens * lp_token_percent)

    with boa.env.anchor():
        # Using remove_liquidity_fixed_out with amount_i = 0
        expected_dy_fixed = gm_pool.calc_withdraw_fixed_out(amount_to_withdraw, i, 0)
        actual_dy_fixed = gm_pool.remove_liquidity_fixed_out(amount_to_withdraw, i, 0, 0)

    with boa.env.anchor():
        # Using remove_liquidity_one_coin for token j
        expected_dy_one = gm_pool.calc_withdraw_one_coin(amount_to_withdraw, j)
        actual_dy_one = gm_pool.remove_liquidity_one_coin(amount_to_withdraw, j, 0)

    # Both methods should return the same amount
    assert (
        expected_dy_fixed == expected_dy_one
    ), "calc_withdraw_fixed_out with amount_i=0 should equal calc_withdraw_one_coin"
    assert (
        actual_dy_fixed == actual_dy_one
    ), "remove_liquidity_fixed_out with amount_i=0 should equal remove_liquidity_one_coin"
