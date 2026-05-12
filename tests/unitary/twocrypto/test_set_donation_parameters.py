import boa
import pytest
from tests.utils.constants import FACTORY_DEPLOYER, PRECISION


def test_default_behavior(pool):
    duration = 100
    period = 120
    threshold = 30 * PRECISION // 100
    max_shares_ratio = 15 * PRECISION // 100

    pool.set_donation_parameters(
        duration,
        period,
        threshold,
        max_shares_ratio,
        sender=FACTORY_DEPLOYER.at(pool.factory()).admin(),
    )

    logs = pool.get_logs()
    assert len(logs) == 1
    assert type(logs[0]).__name__ == "SetDonationParameters"
    assert logs[0].duration == duration
    assert logs[0].donation_protection_period == period
    assert logs[0].donation_protection_lp_threshold == threshold
    assert logs[0].donation_shares_max_ratio == max_shares_ratio

    assert pool.donation_duration() == duration
    assert pool.donation_protection_period() == period
    assert pool.donation_protection_lp_threshold() == threshold
    assert pool.donation_shares_max_ratio() == max_shares_ratio


def test_only_owner(pool):
    with boa.reverts("only owner"):
        pool.set_donation_parameters(100, 120, 1, 1)


@pytest.mark.parametrize(
    "duration,period,threshold,max_shares_ratio,dev_reason",
    [
        (0, 1, 1, 1, '"donation duration cannot be zero"'),
        (1, 0, 1, 1, '"donation protection period cannot be zero"'),
        (1, 1, 0, 1, '"donation protection threshold cannot be zero"'),
        (1, 1, PRECISION + 1, 1, '"donation protection threshold above 1e18"'),
        (1, 1, 1, 0, '"donation shares max ratio cannot be zero"'),
        (1, 1, 1, PRECISION + 1, '"donation shares max ratio above 1e18"'),
    ],
)
def test_invalid_params(pool, duration, period, threshold, max_shares_ratio, dev_reason):
    with boa.reverts(dev=dev_reason):
        pool.set_donation_parameters(
            duration,
            period,
            threshold,
            max_shares_ratio,
            sender=FACTORY_DEPLOYER.at(pool.factory()).admin(),
        )
