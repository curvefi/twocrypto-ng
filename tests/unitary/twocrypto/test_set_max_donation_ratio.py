import boa
from tests.utils.constants import FACTORY_DEPLOYER


def test_default_behavior(pool):
    pool.set_max_donation_ratio(1000, sender=FACTORY_DEPLOYER.at(pool.factory()).admin())

    logs = pool.get_logs()
    assert len(logs) == 1
    assert type(logs[0]).__name__ == "SetMaxDonationRatio"
    assert logs[0].ratio == 1000

    assert pool.max_donation_ratio() == 1000


def test_only_owner(pool):
    with boa.reverts("only owner"):
        pool.set_max_donation_ratio(1000)
