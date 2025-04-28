import pytest
import boa


@pytest.mark.parametrize("amount", [int(i * 10**10 / 4) for i in range(5)])
def test_default_behavior(pool, factory_admin, amount):
    pool.set_admin_fee(amount, sender=factory_admin)


def test_only_owner(pool):
    with boa.reverts("only owner"):
        pool.set_admin_fee(0)


def test_admin_fee_greater_than_max(pool, factory_admin):
    with boa.reverts("admin_fee>MAX"):
        pool.set_admin_fee(10**10 + 1, sender=factory_admin)
