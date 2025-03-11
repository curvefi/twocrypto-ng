import boa
import pytest
from boa.test import strategy
from hypothesis import given, settings

from tests.fixtures.pool import INITIAL_PRICES
from tests.utils import approx

SETTINGS = {"max_examples": 20, "deadline": None}


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

    K0: uint256 = 4 * _xp[0] * _xp[1] // _D * 10**36 // _D
    GK0: uint256  = (
        2 * K0 * K0 // 10**36 * K0 // 10**36
        + (_A_gamma[1] + 10**18)**2
        - K0**2 // 10**36 * (2 * _A_gamma[1] + 3 * 10**18) // 10**18
    )
    NNAG2: uint256 = _A_gamma[0] * _A_gamma[1]**2 // A_MULTIPLIER
    denominator: uint256 = GK0 + NNAG2 * _xp[0] // _D * K0 // 10**36
    numerator: uint256 = _xp[0] * ( GK0 + NNAG2 * _xp[1] // _D * K0 // 10**36 ) // _xp[1]
    return numerator * 10**18 // denominator
"""
    return boa.loads(get_price_impl)


def _get_dydx_vyper(swap, price_calc):
    xp = swap.internal._xp(
        swap._storage.balances.get(),
        swap.price_scale(),
    )

    return price_calc.get_p(xp, swap.D(), swap.internal._A_gamma())


def _get_prices_vyper(swap, price_calc):
    price_token_1_wrt_0 = _get_dydx_vyper(swap, price_calc)
    return price_token_1_wrt_0 * swap.price_scale() // 10**18


def _get_prices_numeric_nofee(swap, views, i):
    if i == 0:  # token at index 1 is being pupmed.
        dx = int(0.01 * 10**36 // INITIAL_PRICES[1])
        dolla_out = views.internal._get_dy_nofee(1, 0, dx, swap)[0]
        price = dolla_out * 10**18 // dx

    else:  # token at index 1 is being dupmed.
        dx = 10**16  # 0.01 USD
        dy = views.internal._get_dy_nofee(0, 1, dx, swap)[0]
        price = dx * 10**18 // dy

    return price


# ----- Tests -----


@given(
    dollar_amount=strategy("decimal", min_value=1e-5, max_value=5e8),
)
@settings(**SETTINGS)
@pytest.mark.parametrize("i", [0, 1])
def test_dxdy_similar(
    yuge_swap,
    dydx_safemath,
    views_contract,
    user,
    dollar_amount,
    coins,
    i,
):
    previous_p = yuge_swap.price_scale()
    j = 1 - i

    amount_in = int(dollar_amount * 10**36 // INITIAL_PRICES[i])
    boa.deal(coins[i], user, amount_in)
    yuge_swap.exchange(i, j, amount_in, 0, sender=user)

    dxdy_vyper = _get_prices_vyper(yuge_swap, dydx_safemath)
    dxdy_swap = yuge_swap.last_prices()  # <-- we check unsafe impl here.
    dxdy_numeric = _get_prices_numeric_nofee(yuge_swap, views_contract, i)

    if i == 0:  # token at index 1 is being pupmed, so last_price should go up
        assert dxdy_swap > previous_p
        assert dxdy_numeric > previous_p
    else:  # token at index 1 is being dupmed, so last_price should go down
        assert dxdy_swap < previous_p
        assert dxdy_numeric < previous_p

    assert dxdy_vyper == dxdy_swap
    assert approx(dxdy_vyper, dxdy_numeric, 1e-5)
