from math import exp, log2

import boa
from boa.test import strategy
from hypothesis import given, settings

from tests.conftest import INITIAL_PRICES
from tests.utils.constants import UNIX_DAY

SETTINGS = {"max_examples": 1000, "deadline": None}


@given(
    token_frac=strategy("uint256", min_value=10**6, max_value=10**16),
    i=strategy("uint8", max_value=1),
)
@settings(**SETTINGS)
def test_last_price_remove_liq(swap_with_deposit, user, token_frac, i):
    prices = INITIAL_PRICES
    token_amount = token_frac * swap_with_deposit.totalSupply() // 10**18

    with boa.env.prank(user):
        swap_with_deposit.remove_liquidity_one_coin(token_amount, i, 0)

    oracle_price = swap_with_deposit.last_prices()
    assert abs(log2(oracle_price / prices[1])) < 0.1


@given(
    amount=strategy(
        "uint256", min_value=10**10, max_value=2 * 10**6 * 10**18
    ),  # Can be more than we have
    i=strategy("uint8", min_value=0, max_value=1),
    t=strategy("uint256", min_value=10, max_value=10 * UNIX_DAY),
)
@settings(**SETTINGS)
def test_ma(swap_with_deposit, coins, user, amount, i, t):
    prices1 = INITIAL_PRICES
    amount = amount * 10**18 // prices1[i]
    boa.deal(coins[i], user, amount)

    rebal_params = swap_with_deposit.internal._unpack_3(
        swap_with_deposit._storage.packed_rebalancing_params.get()
    )
    ma_time = rebal_params[2]

    # here we dont mine because we're time travelling later
    with boa.env.prank(user):
        swap_with_deposit.exchange(i, 1 - i, amount, 0)

    prices2 = swap_with_deposit.last_prices()
    boa.env.time_travel(t)

    with boa.env.prank(user):
        swap_with_deposit.remove_liquidity_one_coin(10**15, 0, 0)

    prices3 = swap_with_deposit.price_oracle()

    # cap new price by 2x previous price oracle value:
    new_price = min(prices2, 2 * prices1[1])

    alpha = exp(-1 * t / ma_time)
    theory = prices1[1] * alpha + new_price * (1 - alpha)
    assert abs(log2(theory / prices3)) < 0.001


# Sanity check for price scale
@given(
    amount=strategy(
        "uint256", min_value=10**10, max_value=2 * 10**6 * 10**18
    ),  # Can be more than we have
    i=strategy("uint8", min_value=0, max_value=1),
    t=strategy("uint256", max_value=10 * UNIX_DAY),
)
@settings(**SETTINGS)
def test_price_scale_range(swap_with_deposit, coins, user, amount, i, t):
    prices1 = INITIAL_PRICES
    amount = amount * 10**18 // prices1[i]
    boa.deal(coins[i], user, amount)

    with boa.env.prank(user):
        swap_with_deposit.exchange(i, 1 - i, amount, 0)

    prices2 = swap_with_deposit.last_prices()
    boa.env.time_travel(seconds=t)

    with boa.env.prank(user):
        swap_with_deposit.remove_liquidity_one_coin(10**15, 0, 0)

    prices3 = swap_with_deposit.price_scale()

    if prices1[1] > prices2:
        assert prices3 <= prices1[1] and prices3 >= prices2
    else:
        assert prices3 >= prices1[1] and prices3 <= prices2
