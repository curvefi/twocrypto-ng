from math import log

import boa
import pytest
from boa.test import strategy
from hypothesis import given, settings

from tests.fixtures.pool import INITIAL_PRICES
from tests.utils.tokens import mint_for_testing

SETTINGS = {"max_examples": 100, "deadline": None}


# flake8: noqa: E501
@pytest.fixture(scope="module")
def dydx_safemath():

    get_price_impl = """
N_COINS: constant(uint256) = 2
A_MULTIPLIER: constant(uint256) = 10000

@external
@view
def get_p(
    _xp: uint256[N_COINS], _D: uint256, _A_gamma: uint256[N_COINS]
) -> uint256:

    assert _D > 10**17 - 1 and _D < 10**15 * 10**18 + 1  # dev: unsafe D values

    K0: uint256 = 4 * _xp[0] * _xp[1] / _D * 10**36 / _D
    GK0: uint256  = (
        2 * K0 * K0 / 10**36 * K0 / 10**36
        + (_A_gamma[1] + 10**18)**2
        - K0**2 / 10**36 * (2 * _A_gamma[1] + 3 * 10**18) / 10**18
    )
    NNAG2: uint256 = _A_gamma[0] * _A_gamma[1]**2 / A_MULTIPLIER
    denominator: uint256 = GK0 + NNAG2 * _xp[0] / _D * K0 / 10**36
    return _xp[0] * ( GK0 + NNAG2 * _xp[1] / _D * K0 / 10**36 ) / _xp[1] * 10**18 / denominator
"""
    return boa.loads(get_price_impl)


def _get_dydx_vyper(swap, price_calc):

    xp = swap.internal.xp(
        swap._storage.balances.get(),
        swap.price_scale(),
    )

    return price_calc.get_p(xp, swap.D(), swap.internal._A_gamma())


def _get_prices_vyper(swap, price_calc):

    price_token_1_wrt_0 = _get_dydx_vyper(swap, price_calc)
    return price_token_1_wrt_0 * swap.price_scale() // 10**18


def _get_prices_numeric_nofee(swap, views, sell_usd):

    if sell_usd:

        dx = 10**16  # 0.01 USD
        dy = (views.internal._get_dy_nofee(0, 1, dx, swap)[0],)
        price = dx * 10**18 // dy[0]

    else:

        dx = int(0.01 * 10**36 // INITIAL_PRICES[1])
        dolla_out = views.internal._get_dy_nofee(1, 0, dx, swap)[0]
        price = dolla_out * 10**18 // dx

    return price


# ----- Tests -----


@given(
    dollar_amount=strategy(
        "uint256", min_value=5 * 10**4, max_value=5 * 10**8
    ),
)
@settings(**SETTINGS)
@pytest.mark.parametrize("i", [0, 1])
@pytest.mark.parametrize("j", [0, 1])
def test_dxdy_similar(
    yuge_swap,
    dydx_safemath,
    views_contract,
    user,
    dollar_amount,
    coins,
    i,
    j,
):

    if i == j:
        return

    dx = dollar_amount * 10**36 // INITIAL_PRICES[i]
    mint_for_testing(coins[i], user, dx)

    with boa.env.prank(user):
        yuge_swap.exchange(i, j, dx, 0)

    dxdy_vyper = _get_prices_vyper(yuge_swap, dydx_safemath)
    dxdy_numeric_nofee = _get_prices_numeric_nofee(
        yuge_swap, views_contract, sell_usd=(i == 0)
    )

    assert abs(log(dxdy_vyper / dxdy_numeric_nofee)) < 1e-5

    dxdy_swap = yuge_swap.last_prices()  # <-- we check unsafe impl here.
    assert abs(log(dxdy_vyper / dxdy_swap)) < 1e-5


@given(
    dollar_amount=strategy(
        "uint256", min_value=10**4, max_value=4 * 10**5
    ),
)
@settings(**SETTINGS)
def test_dxdy_pump(yuge_swap, dydx_safemath, user, dollar_amount, coins):

    dxdy_math_0 = _get_prices_vyper(yuge_swap, dydx_safemath)
    dxdy_swap_0 = yuge_swap.last_prices()

    dx = dollar_amount * 10**18
    mint_for_testing(coins[0], user, dx)

    with boa.env.prank(user):
        yuge_swap.exchange(0, 1, dx, 0)

    dxdy_math_1 = _get_prices_vyper(yuge_swap, dydx_safemath)
    dxdy_swap_1 = yuge_swap.last_prices()

    assert dxdy_math_1 > dxdy_math_0
    assert dxdy_swap_1 > dxdy_swap_0


@given(
    dollar_amount=strategy(
        "uint256", min_value=10**4, max_value=4 * 10**5
    ),
)
@settings(**SETTINGS)
def test_dxdy_dump(yuge_swap, dydx_safemath, user, dollar_amount, coins):

    dxdy_math_0 = _get_prices_vyper(yuge_swap, dydx_safemath)
    dxdy_swap_0 = yuge_swap.last_prices()

    dx = dollar_amount * 10**36 // INITIAL_PRICES[1]
    mint_for_testing(coins[1], user, dx)

    with boa.env.prank(user):
        yuge_swap.exchange(1, 0, dx, 0)

    dxdy_math_1 = _get_prices_vyper(yuge_swap, dydx_safemath)
    dxdy_swap_1 = yuge_swap.last_prices()

    assert dxdy_math_1 < dxdy_math_0
    assert dxdy_swap_1 < dxdy_swap_0
