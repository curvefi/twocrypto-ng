import boa

from tests.utils.constants import ZERO_ADDRESS


def test_default_fee_receiver_is_factory(pool, factory):
    assert pool.pool_fee_receiver() == ZERO_ADDRESS
    assert pool.fee_receiver() == factory.fee_receiver()


def test_set_pool_fee_receiver(pool, factory_admin):
    new_receiver = boa.env.generate_address()

    with boa.env.prank(factory_admin):
        pool.set_fee_receiver(new_receiver)

    assert pool.pool_fee_receiver() == new_receiver
    assert pool.fee_receiver() == new_receiver


def test_set_pool_fee_receiver_emits_event(pool, factory_admin):
    new_receiver = boa.env.generate_address()

    with boa.env.prank(factory_admin):
        pool.set_fee_receiver(new_receiver)

    logs = pool.get_logs()
    assert len(logs) == 1
    assert logs[0].old_receiver == ZERO_ADDRESS
    assert logs[0].new_receiver == new_receiver


def test_update_pool_fee_receiver(pool, factory_admin):
    first_receiver = boa.env.generate_address()
    second_receiver = boa.env.generate_address()

    with boa.env.prank(factory_admin):
        pool.set_fee_receiver(first_receiver)
        pool.set_fee_receiver(second_receiver)

    logs = pool.get_logs()
    assert pool.fee_receiver() == second_receiver
    assert logs[-1].old_receiver == first_receiver
    assert logs[-1].new_receiver == second_receiver


def test_reset_to_factory_fee_receiver(pool, factory, factory_admin):
    custom_receiver = boa.env.generate_address()

    with boa.env.prank(factory_admin):
        pool.set_fee_receiver(custom_receiver)
        assert pool.fee_receiver() == custom_receiver

        pool.set_fee_receiver(ZERO_ADDRESS)
        assert pool.pool_fee_receiver() == ZERO_ADDRESS
        assert pool.fee_receiver() == factory.fee_receiver()


def test_non_admin_cannot_set_fee_receiver(pool, user):
    new_receiver = boa.env.generate_address()

    with boa.reverts("only owner"):
        with boa.env.prank(user):
            pool.set_fee_receiver(new_receiver)


def test_pool_fee_receiver_overrides_factory_change(pool, factory, factory_admin):
    pool_receiver = boa.env.generate_address()
    new_factory_receiver = boa.env.generate_address()

    with boa.env.prank(factory_admin):
        pool.set_fee_receiver(pool_receiver)
        factory.set_fee_receiver(new_factory_receiver)

    assert pool.fee_receiver() == pool_receiver
    assert factory.fee_receiver() == new_factory_receiver


def test_claim_admin_fees_uses_pool_receiver(pool_with_deposit, coins, factory_admin, user):
    pool_receiver = boa.env.generate_address()

    with boa.env.prank(factory_admin):
        pool_with_deposit.set_fee_receiver(pool_receiver)

    swap_amount = 10**18
    boa.deal(coins[0], user, swap_amount)

    with boa.env.prank(user):
        coins[0].approve(pool_with_deposit.address, swap_amount)
        pool_with_deposit.exchange(0, 1, swap_amount, 0)

    boa.env.time_travel(seconds=86400 + 1)

    initial_balance_0 = coins[0].balanceOf(pool_receiver)
    initial_balance_1 = coins[1].balanceOf(pool_receiver)

    with boa.env.prank(user):
        pool_with_deposit.remove_liquidity_one_coin(1, 0, 0)

    final_balance_0 = coins[0].balanceOf(pool_receiver)
    final_balance_1 = coins[1].balanceOf(pool_receiver)

    assert final_balance_0 > initial_balance_0 or final_balance_1 > initial_balance_1
