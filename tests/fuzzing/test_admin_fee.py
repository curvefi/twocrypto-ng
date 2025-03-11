import boa
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.fixtures.pool import INITIAL_PRICES


@given(ratio=st.floats(min_value=0.0001, max_value=0.1))
@settings(max_examples=10, deadline=None)
def test_admin_fee_after_deposit(swap, coins, fee_receiver, user, user_b, ratio):
    quantities = [10**42 // p for p in INITIAL_PRICES]

    for coin, q in zip(coins, quantities):
        for u in [user, user_b]:
            boa.deal(coin, u, q)
            with boa.env.prank(u):
                coin.approve(swap, 2**256 - 1)

    split_quantities = [quantities[0] // 100, quantities[1] // 100]

    with boa.env.prank(user):
        swap.add_liquidity(split_quantities, 0)

    with boa.env.prank(user_b):
        for _ in range(100):
            before = coins[1].balanceOf(user_b)
            swap.exchange(0, 1, split_quantities[0] // 100, 0)
            after = coins[1].balanceOf(user_b)
            to_swap = after - before
            swap.exchange(1, 0, to_swap, 0)

    balances = [swap.balances(i) for i in range(2)]
    split_quantities = [int(balances[0] * ratio), int(balances[1] * ratio)]
    with boa.env.prank(user):
        swap.add_liquidity(split_quantities, 0)

    assert coins[0].balanceOf(fee_receiver) + coins[1].balanceOf(fee_receiver) == 0

    return swap
