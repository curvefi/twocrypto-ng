import boa


NEW_ADMIN_FEE = 3 * 10**9


def _generate_fee_activity(pool, coins, depositor, trader):
    amounts = [10**24, 10**24]

    for coin, amount in zip(coins, amounts):
        for account in (depositor, trader):
            boa.deal(coin, account, amount)
            with boa.env.prank(account):
                coin.approve(pool, 2**256 - 1)

    with boa.env.prank(depositor):
        pool.add_liquidity(amounts, 0)

    with boa.env.prank(trader):
        for _ in range(20):
            pool.exchange(0, 1, amounts[0] // 100, 0)
            pool.exchange(1, 0, amounts[1] // 100, 0)


def test_admin_fee_default(pool):
    assert pool.admin_fee() == 5 * 10**9


def test_admin_fee_update(factory_admin, pool):
    with boa.env.prank(factory_admin):
        pool.set_admin_fee(NEW_ADMIN_FEE)

    assert pool.admin_fee() == NEW_ADMIN_FEE


def test_admin_fee_reverts_for_non_admin(user, pool):
    with boa.reverts(), boa.env.prank(user):
        pool.set_admin_fee(NEW_ADMIN_FEE)


def test_admin_fee_reverts_above_cap(factory_admin, pool):
    with boa.env.prank(factory_admin):
        with boa.reverts():
            pool.set_admin_fee(10**10 + 1)


def test_admin_fee_claims_with_new_rate(
    pool_with_deposit,
    coins,
    factory_admin,
    fee_receiver,
    user,
    bob,
):
    pool = pool_with_deposit

    _generate_fee_activity(pool, coins, user, bob)
    boa.env.time_travel(86401)

    balances_before = [coin.balanceOf(fee_receiver) for coin in coins]

    with boa.env.prank(factory_admin):
        pool.set_admin_fee(NEW_ADMIN_FEE)

    lp_balance = pool.balanceOf(user)
    withdraw_amount = max(lp_balance // 200, 10**16)

    with boa.env.prank(user):
        pool.remove_liquidity_one_coin(withdraw_amount, 0, 0)

    balances_after = [coin.balanceOf(fee_receiver) for coin in coins]

    assert pool.admin_fee() == NEW_ADMIN_FEE
    assert balances_after[0] > balances_before[0] or balances_after[1] > balances_before[1]
