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
def test_withdraw_full(i, gm_pool):
    j = 1 - i

    lp_tokens = gm_pool.balanceOf(boa.env.eoa)

    # 75% of the lp tokens because 100% would leave the pool with 0 liquidity
    # in the i coin
    amount_to_withdraw = int(lp_tokens * 0.75)

    t0 = gm_pool.balances_snapshot()

    expected_dy = gm_pool.calc_withdraw_one_coin(amount_to_withdraw, i)

    actual_dy = gm_pool.remove_liquidity_one_coin(amount_to_withdraw, i, 0)

    t1 = gm_pool.balances_snapshot()

    assert (
        actual_dy == expected_dy
    ), "calc_withdraw_one_coin and remove_liquidity_one_coin do not match"

    assert (
        t1["lp_supply"] == t0["lp_supply"] - amount_to_withdraw
    ), "pool lp balance did not decrease after removing liquidity"
    assert (
        t1["user_lp"] == t0["user_lp"] - amount_to_withdraw
    ), "user lp balance did not decrease after removing liquidity"

    assert (
        t1["user_coins"][i] == t0["user_coins"][i] + actual_dy
    ), "user i coin balance did not increase after removing liquidity"
    assert (
        t1["user_coins"][j] == t0["user_coins"][j]
    ), "user j coin balance did not remain the same after removing liquidity"

    assert (
        actual_dy == t0["pool_coins"][i] - t1["pool_coins"][i]
    ), "pool i coin balance did not decrease after removing liquidity"
    assert (
        t1["pool_coins"][j] == t0["pool_coins"][j]
    ), "pool j coin balance did not remain the same after removing liquidity"


@pytest.mark.parametrize("i", range(N_COINS))
def test_slippage_failure(i, gm_pool):
    lp_tokens = gm_pool.balanceOf(boa.env.eoa)

    # 75% of the lp tokens because 100% would leave the pool with 0 liquidity
    # in the i coin
    amount_to_withdraw = int(lp_tokens * 0.75)

    with boa.env.anchor():
        expected_dy = gm_pool.remove_liquidity_one_coin(amount_to_withdraw, i, 0)

    with boa.env.anchor():
        # This should not revert
        gm_pool.remove_liquidity_one_coin(amount_to_withdraw, i, expected_dy)

    with boa.reverts("slippage"):
        gm_pool.remove_liquidity_one_coin(amount_to_withdraw, i, expected_dy + 1)


def test_withdraw_more_than_owned(gm_pool):
    # TODO move to calc tests
    lp_tokens = gm_pool.balanceOf(boa.env.eoa)

    amount_to_withdraw = lp_tokens + 1

    with boa.reverts("withdraw > supply"):
        gm_pool.remove_liquidity_one_coin(amount_to_withdraw, 0, 0)


def test_withdraw_wrong_coin_index(gm_pool):
    # TODO move to calc tests
    with boa.reverts("safesub"):
        gm_pool.remove_liquidity_one_coin(100, 2, 0)
