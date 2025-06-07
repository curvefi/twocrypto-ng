import boa
from tests.utils.constants import FACTORY_DEPLOYER


def test_default_behavior(pool):
    pool.set_donation_fee_multiplier(1 * 10**10, sender=FACTORY_DEPLOYER.at(pool.factory()).admin())

    logs = pool.get_logs()
    assert len(logs) == 1
    assert type(logs[0]).__name__ == "SetDonationFeeMultiplier"
    assert logs[0].fee_multiplier == 1 * 10**10

    assert pool.donation_fee_multiplier() == 1 * 10**10


def test_only_owner(pool):
    with boa.reverts("only owner"):
        pool.set_donation_fee_multiplier(1 * 10**10)
