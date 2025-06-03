import boa
from pytest import fixture
import pytest


@fixture(scope="module")
def gm_pool(gm_pool):
    # We seed the pool with 200 dollars worth of liquidity
    gm_pool.add_liquidity_balanced(100 * 10**18)
    return gm_pool


@pytest.mark.parametrize("method", ["fixed_out", "one_coin"])
def test_withdraw_more_than_supply(gm_pool, method):
    lp_tokens = gm_pool.balanceOf(boa.env.eoa)
    amount_to_withdraw = lp_tokens + 1

    with boa.reverts("withdraw > supply"):
        if method == "fixed_out":
            gm_pool.calc_withdraw_fixed_out(amount_to_withdraw, 0, 0)
        else:
            gm_pool.calc_withdraw_one_coin(amount_to_withdraw, 0)


@pytest.mark.parametrize("method", ["fixed_out", "one_coin"])
def test_withdraw_wrong_coin_index(gm_pool, method):
    with boa.reverts():
        if method == "fixed_out":
            gm_pool.calc_withdraw_fixed_out(100, 2, 0)
        else:
            gm_pool.calc_withdraw_one_coin(100, 2)
