import math

import boa
import pytest
from boa.test import strategy
from hypothesis import given, settings

from tests.fixtures.pool import INITIAL_PRICES
from tests.utils import simulation_int_many as sim
from tests.utils.tokens import mint_for_testing

SETTINGS = {"max_examples": 100, "deadline": None}


@pytest.fixture(scope="module")
def test_deposit(swap, coins, user, fee_receiver):

    quantities = [10**36 // p for p in INITIAL_PRICES]  # $3M worth

    for coin, q in zip(coins, quantities):
        mint_for_testing(coin, user, q)
        with boa.env.prank(user):
            coin.approve(swap, 2**256 - 1)

    bal_before = boa.env.get_balance(swap.address)
    with boa.env.prank(user):
        swap.add_liquidity(quantities, 0)

    # test if eth wasnt deposited:
    assert boa.env.get_balance(swap.address) == bal_before

    token_balance = swap.balanceOf(user)
    assert (
        token_balance == swap.totalSupply() - swap.balanceOf(fee_receiver) > 0
    )
    assert abs(swap.get_virtual_price() / 1e18 - 1) < 1e-3
