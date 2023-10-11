# flake8: noqa
import boa
from boa.test import strategy
from hypothesis import given, settings  # noqa

from tests.fixtures.pool import INITIAL_PRICES
from tests.utils.tokens import mint_for_testing

SETTINGS = {"max_examples": 100, "deadline": None}


@given(
    amount=strategy(
        "uint256", min_value=10**10, max_value=10**6 * 10**18
    ),
    split_in=strategy("uint256", min_value=0, max_value=100),
    split_out=strategy("uint256", min_value=0, max_value=100),
    i=strategy("uint", min_value=0, max_value=1),
    j=strategy("uint", min_value=0, max_value=1),
)
@settings(**SETTINGS)
def test_exchange_split(
    swap_with_deposit,
    views_contract,
    coins,
    user,
    amount,
    split_in,
    split_out,
    i,
    j,
):
    pass
