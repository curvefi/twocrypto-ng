from math import exp, log, log2, sqrt

import boa
import pytest
from boa.test import strategy
from hypothesis import given, settings

from tests.fixtures.pool import INITIAL_PRICES
from tests.utils.tokens import mint_for_testing

SETTINGS = {"max_examples": 1000, "deadline": None}


def approx(x1, x2, precision):
    return abs(log(x1 / x2)) <= precision


def norm(price_oracle, price_scale):
    norm = 0
    ratio = price_oracle * 10**18 / price_scale
    if ratio > 10**18:
        ratio -= 10**18
    else:
        ratio = 10**18 - ratio
    norm += ratio**2
    return sqrt(norm)


def test_initial(swap_with_deposit):
    assert swap_with_deposit.price_scale() == INITIAL_PRICES[1]
    assert swap_with_deposit.price_oracle() == INITIAL_PRICES[1]


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
    t=strategy("uint256", min_value=10, max_value=10 * 86400),
)
@settings(**SETTINGS)
def test_ma(swap_with_deposit, coins, user, amount, i, t):

    prices1 = INITIAL_PRICES
    amount = amount * 10**18 // prices1[i]
    mint_for_testing(coins[i], user, amount)

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


@given(
    amount=strategy(
        "uint256", min_value=10**10, max_value=2 * 10**6 * 10**18
    ),  # Can be more than we have
    i=strategy("uint8", min_value=0, max_value=1),
    t=strategy("uint256", min_value=10, max_value=10 * 86400),
)
@settings(**SETTINGS)
def test_xcp_ma(swap_with_deposit, coins, user, amount, i, t):

    price_scale = swap_with_deposit.price_scale()
    D0 = swap_with_deposit.D()
    xp = [0, 0]
    xp[0] = D0 // 2  # N_COINS = 2
    xp[1] = D0 * 10**18 // (2 * price_scale)

    xcp0 = boa.eval(f"isqrt({xp[0]*xp[1]})")

    # after first deposit anf before any swaps:
    # xcp oracle is equal to totalSupply
    assert xcp0 == swap_with_deposit.totalSupply()

    amount = amount * 10**18 // INITIAL_PRICES[i]
    mint_for_testing(coins[i], user, amount)

    ma_time = swap_with_deposit.xcp_ma_time()

    # swap to populate
    with boa.env.prank(user):
        swap_with_deposit.exchange(i, 1 - i, amount, 0)

    xcp1 = swap_with_deposit.last_xcp()
    tvl = (
        swap_with_deposit.virtual_price()
        * swap_with_deposit.totalSupply()
        // 10**18
    )
    assert approx(xcp1, tvl, 1e-10)

    boa.env.time_travel(t)

    with boa.env.prank(user):
        swap_with_deposit.remove_liquidity_one_coin(10**15, 0, 0)

    xcp2 = swap_with_deposit.xcp_oracle()

    alpha = exp(-1 * t / ma_time)
    theory = xcp0 * alpha + xcp1 * (1 - alpha)

    assert approx(theory, xcp2, 1e-10)


# Sanity check for price scale
@given(
    amount=strategy(
        "uint256", min_value=10**10, max_value=2 * 10**6 * 10**18
    ),  # Can be more than we have
    i=strategy("uint8", min_value=0, max_value=1),
    t=strategy("uint256", max_value=10 * 86400),
)
@settings(**SETTINGS)
def test_price_scale_range(swap_with_deposit, coins, user, amount, i, t):

    prices1 = INITIAL_PRICES
    amount = amount * 10**18 // prices1[i]
    mint_for_testing(coins[i], user, amount)

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


@pytest.mark.parametrize("i", [0, 1])
def test_price_scale_change(swap_with_deposit, i, coins, users):
    j = 1 - i
    amount = 10**6 * 10**18
    t = 86400
    user = users[1]
    prices1 = INITIAL_PRICES
    amount = amount * 10**18 // prices1[i]
    mint_for_testing(coins[i], user, amount)
    mint_for_testing(coins[j], user, amount)
    coins[i].approve(swap_with_deposit, 2**256 - 1, sender=user)
    coins[j].approve(swap_with_deposit, 2**256 - 1, sender=user)

    out = swap_with_deposit.exchange(i, j, amount, 0, sender=user)
    swap_with_deposit.exchange(j, i, int(out * 0.95), 0, sender=user)
    price_scale_1 = swap_with_deposit.price_scale()

    boa.env.time_travel(t)

    swap_with_deposit.exchange(0, 1, coins[0].balanceOf(user), 0, sender=user)

    price_oracle = swap_with_deposit.price_oracle()
    rebal_params = swap_with_deposit.internal._unpack_3(
        swap_with_deposit._storage.packed_rebalancing_params.get()
    )
    _norm = norm(price_oracle, price_scale_1)
    step = max(rebal_params[1], _norm / 5)
    price_scale_2 = swap_with_deposit.price_scale()

    price_diff = abs(price_scale_2 - price_scale_1)
    adjustment = int(step * abs(price_oracle - price_scale_1) / _norm)
    assert price_diff > 0
    assert approx(adjustment, price_diff, 0.01)
    assert approx(
        swap_with_deposit.virtual_price(),
        swap_with_deposit.get_virtual_price(),
        1e-10,
    )


def test_lp_price(swap_with_deposit):
    tvl = (
        swap_with_deposit.balances(0)
        + swap_with_deposit.balances(1)
        * swap_with_deposit.price_scale()
        // 10**18
    )
    naive_price = tvl * 10**18 // swap_with_deposit.totalSupply()
    assert approx(naive_price, swap_with_deposit.lp_price(), 0)
