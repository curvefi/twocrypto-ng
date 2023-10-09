import boa
from boa.test import strategy
from hypothesis import given, settings  # noqa

from tests.fixtures.pool import INITIAL_PRICES
from tests.utils.tokens import mint_for_testing

SETTINGS = {"max_examples": 100, "deadline": None}


@given(
    amount=strategy(
        "uint256", min_value=10**10, max_value=10**6 * 10**18
    ),  # Can be more than we have
    i=strategy("uint", min_value=0, max_value=2),
    j=strategy("uint", min_value=0, max_value=2),
)
@settings(**SETTINGS)
def test_exchange_all(
    swap_with_deposit,
    views_contract,
    coins,
    user,
    amount,
    i,
    j,
):

    if i == j or i > len(coins) - 1 or j > len(coins) - 1:

        with boa.reverts():
            views_contract.get_dy(i, j, 10**6, swap_with_deposit)

        with boa.reverts(), boa.env.prank(user):
            swap_with_deposit.exchange(i, j, 10**6, 0)

    else:

        amount = amount * 10**18 // INITIAL_PRICES[i]
        mint_for_testing(coins[i], user, amount)

        calculated = views_contract.get_dy(i, j, amount, swap_with_deposit)

        measured_i = coins[i].balanceOf(user)
        measured_j = coins[j].balanceOf(user)
        d_balance_i = swap_with_deposit.balances(i)
        d_balance_j = swap_with_deposit.balances(j)

        with boa.env.prank(user):
            swap_with_deposit.exchange(i, j, amount, int(0.999 * calculated))

        measured_i -= coins[i].balanceOf(user)
        measured_j = coins[j].balanceOf(user) - measured_j
        d_balance_i = swap_with_deposit.balances(i) - d_balance_i
        d_balance_j = swap_with_deposit.balances(j) - d_balance_j

        assert amount == measured_i
        assert calculated == measured_j

        assert d_balance_i == amount
        assert -d_balance_j == measured_j


@given(
    amount=strategy(
        "uint256", min_value=10**10, max_value=10**6 * 10**18
    ),  # Can be more than we have
    i=strategy("uint", min_value=0, max_value=2),
    j=strategy("uint", min_value=0, max_value=2),
)
@settings(**SETTINGS)
def test_exchange_received_success(
    swap_with_deposit,
    views_contract,
    coins,
    user,
    amount,
    i,
    j,
):

    if i == j or i > len(coins) - 1 or j > len(coins) - 1:
        return

    amount = amount * 10**18 // INITIAL_PRICES[i]
    mint_for_testing(coins[i], user, amount)

    calculated = views_contract.get_dy(i, j, amount, swap_with_deposit)

    measured_i = coins[i].balanceOf(user)
    measured_j = coins[j].balanceOf(user)
    d_balance_i = swap_with_deposit.balances(i)
    d_balance_j = swap_with_deposit.balances(j)

    with boa.env.prank(user):
        coins[i].transfer(swap_with_deposit, amount)
        swap_with_deposit.exchange_received(
            i, j, amount, int(0.999 * calculated), user
        )

    measured_i -= coins[i].balanceOf(user)
    measured_j = coins[j].balanceOf(user) - measured_j
    d_balance_i = swap_with_deposit.balances(i) - d_balance_i
    d_balance_j = swap_with_deposit.balances(j) - d_balance_j

    assert amount == measured_i
    assert calculated == measured_j

    assert d_balance_i == amount
    assert -d_balance_j == measured_j
    print("pass!")


@given(
    amount=strategy(
        "uint256", min_value=10**10, max_value=10**6 * 10**18
    ),  # Can be more than we have
    i=strategy("uint", min_value=0, max_value=2),
    j=strategy("uint", min_value=0, max_value=2),
)
@settings(**SETTINGS)
def test_exchange_received_revert_on_no_transfer(
    swap_with_deposit,
    views_contract,
    coins,
    user,
    amount,
    i,
    j,
):

    if i == j or i > len(coins) or j > len(coins):

        return

    amount = amount * 10**18 // INITIAL_PRICES[i]
    mint_for_testing(coins[i], user, amount)

    calculated = views_contract.get_dy(i, j, amount, swap_with_deposit)

    with boa.env.prank(user), boa.reverts(dev="user didn't give us coins"):
        swap_with_deposit.exchange_received(
            i, j, amount, int(0.999 * calculated), user
        )
