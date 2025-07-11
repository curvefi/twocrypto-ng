import boa
import pytest
from tests.utils.constants import FACTORY_DEPLOYER, PRECISION


def test_default_behavior(pool):
    period = 120
    threshold = 30 * PRECISION // 100
    max_shares_ratio = 15 * PRECISION // 100

    pool.set_donation_protection_params(
        period, threshold, max_shares_ratio, sender=FACTORY_DEPLOYER.at(pool.factory()).admin()
    )

    logs = pool.get_logs()
    assert len(logs) == 1
    assert type(logs[0]).__name__ == "SetDonationProtection"
    assert logs[0].donation_protection_period == period
    assert logs[0].donation_protection_lp_threshold == threshold
    assert logs[0].donation_shares_max_ratio == max_shares_ratio

    assert pool.donation_protection_period() == period
    assert pool.donation_protection_lp_threshold() == threshold
    assert pool.donation_shares_max_ratio() == max_shares_ratio


def test_only_owner(pool):
    with boa.reverts("only owner"):
        pool.set_donation_protection_params(120, 1, 1)


@pytest.mark.parametrize("period,threshold,max_shares", [(0, 1, 1), (1, 0, 1), (1, 1, 0)])
def test_invalid_params(pool, owner, period, threshold, max_shares):
    revert_msgs = {
        (0, 1, 1): "period must be positive",
        (1, 0, 1): "threshold must be positive",
        (1, 1, 0): "max_shares must be positive",
    }
    with boa.reverts(revert_msgs[(period, threshold, max_shares)]):
        pool.set_donation_protection_params(
            period, threshold, max_shares, sender=FACTORY_DEPLOYER.at(pool.factory()).admin()
        )
