import boa
import pytest

from tests.utils.constants import PRECISION


@pytest.mark.parametrize("admin_fee", [int(i * 10**10 / 4) for i in range(5)])
@pytest.mark.parametrize("lp_profit_fraction", [0, PRECISION // 2, PRECISION])
def test_default_behavior(pool, factory_admin, admin_fee, lp_profit_fraction):
    pool.set_fee_parameters(admin_fee, lp_profit_fraction, sender=factory_admin)

    logs = pool.get_logs()
    assert len(logs) == 1
    assert type(logs[0]).__name__ == "SetFeeParameters"
    assert logs[0].admin_fee == admin_fee
    assert logs[0].lp_profit_fraction == lp_profit_fraction

    assert pool.admin_fee() == admin_fee
    assert pool.lp_profit_fraction() == lp_profit_fraction


def test_only_owner(pool):
    with boa.reverts("only owner"):
        pool.set_fee_parameters(0, 0)


def test_admin_fee_greater_than_max(pool, factory_admin):
    with boa.reverts(dev='"admin fee above max"'):
        pool.set_fee_parameters(10**10 + 1, 0, sender=factory_admin)


def test_lp_profit_fraction_greater_than_precision(pool, factory_admin):
    with boa.reverts(dev='"lp profit fraction above 1e18"'):
        pool.set_fee_parameters(0, PRECISION + 1, sender=factory_admin)
