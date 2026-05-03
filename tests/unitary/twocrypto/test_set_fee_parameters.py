import boa
import pytest

from tests.utils.constants import FEE_PRECISION


@pytest.mark.parametrize("admin_fee", [int(i * 10**10 / 4) for i in range(5)])
@pytest.mark.parametrize("reserved_profit_fraction", [0, FEE_PRECISION // 2, FEE_PRECISION])
def test_default_behavior(pool, factory_admin, admin_fee, reserved_profit_fraction):
    pool.set_fee_parameters(reserved_profit_fraction, admin_fee, sender=factory_admin)

    logs = pool.get_logs()
    assert len(logs) == 1
    assert type(logs[0]).__name__ == "SetFeeParameters"
    assert logs[0].admin_fee == admin_fee
    assert logs[0].reserved_profit_fraction == reserved_profit_fraction

    assert pool.admin_fee() == admin_fee
    assert pool.reserved_profit_fraction() == reserved_profit_fraction


def test_only_owner(pool):
    with boa.reverts("only owner"):
        pool.set_fee_parameters(0, 0)


def test_admin_fee_greater_than_max(pool, factory_admin):
    with boa.reverts(dev='"admin fee above max"'):
        pool.set_fee_parameters(0, 10**10 + 1, sender=factory_admin)


def test_reserved_profit_fraction_greater_than_precision(pool, factory_admin):
    with boa.reverts(dev='"reserved profit fraction above 1e10"'):
        pool.set_fee_parameters(FEE_PRECISION + 1, 0, sender=factory_admin)
