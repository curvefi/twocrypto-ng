import boa

from tests.fixtures.pool import INITIAL_PRICES
from tests.utils.tokens import mint_for_testing


def test_no_steal_from_wallet(swap, coins, user, hacker):
    quantities = [10**36 // p for p in INITIAL_PRICES]  # $3M worth

    for coin, q in zip(coins, quantities):
        mint_for_testing(coin, user, q)
        with boa.env.prank(user):
            coin.approve(swap, 2**256 - 1)

    split_quantities = [quantities[0] // 2, quantities[1] // 2]
    with boa.env.prank(user):
        swap.add_liquidity(split_quantities, 0)
        swap.deposit_to_spot_wallet(split_quantities, user)

    with boa.env.prank(hacker), boa.reverts(dev="user didn't give us coins"):
        swap.exchange_received(0, 1, 10**17, 0, hacker)
