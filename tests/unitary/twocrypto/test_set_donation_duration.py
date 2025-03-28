import boa
from tests.utils.constants import FACTORY_DEPLOYER


def test_default_behavior(pool):
    pool.set_donation_duration(100, sender=FACTORY_DEPLOYER.at(pool.factory()).admin())

    logs = pool.get_logs()
    assert len(logs) == 1
    assert type(logs[0]).__name__ == "SetDonationDuration"
    assert logs[0].duration == 100

    assert pool.donation_duration() == 100


def test_only_owner(pool):
    with boa.reverts("only owner"):
        pool.set_donation_duration(100)
