import boa

from tests.utils.tokens import mint_for_testing


NEW_ADMIN_FEE = 3 * 10**9


def _generate_fee_activity(swap, coins, depositor, trader):
    amounts = [10**24, 10**24]

    for coin, amount in zip(coins, amounts):
        for account in (depositor, trader):
            mint_for_testing(coin, account, amount)
            with boa.env.prank(account):
                coin.approve(swap, 2**256 - 1)

    with boa.env.prank(depositor):
        swap.add_liquidity(amounts, 0)

    with boa.env.prank(trader):
        for _ in range(20):
            swap.exchange(0, 1, amounts[0] // 100, 0)
            swap.exchange(1, 0, amounts[1] // 100, 0)


def test_admin_fee_default(swap):
    assert swap.admin_fee() == 5 * 10**9


def test_admin_fee_update(factory_admin, swap):
    with boa.env.prank(factory_admin):
        swap.set_admin_fee(NEW_ADMIN_FEE)

    assert swap.admin_fee() == NEW_ADMIN_FEE


def test_admin_fee_reverts_for_non_admin(user, swap):
    with boa.reverts(), boa.env.prank(user):
        swap.set_admin_fee(NEW_ADMIN_FEE)


def test_admin_fee_reverts_above_cap(factory_admin, swap):
    with boa.env.prank(factory_admin):
        with boa.reverts():
            swap.set_admin_fee(10**10 + 1)


def test_admin_fee_claims_with_new_rate(
    swap_with_deposit,
    coins,
    factory_admin,
    fee_receiver,
    user,
    user_b,
):
    swap = swap_with_deposit

    _generate_fee_activity(swap, coins, user, user_b)
    boa.env.time_travel(86401)

    balances_before = [coin.balanceOf(fee_receiver) for coin in coins]

    with boa.env.prank(factory_admin):
        swap.set_admin_fee(NEW_ADMIN_FEE)

    lp_balance = swap.balanceOf(user)
    withdraw_amount = max(lp_balance // 200, 10**16)

    with boa.env.prank(user):
        swap.remove_liquidity_one_coin(withdraw_amount, 0, 0)

    balances_after = [coin.balanceOf(fee_receiver) for coin in coins]

    assert swap.admin_fee() == NEW_ADMIN_FEE
    assert balances_after[0] > balances_before[0] or balances_after[1] > balances_before[1]
