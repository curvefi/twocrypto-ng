import boa
import boa_zksync
import pytest
from boa_zksync import EraTestNode
from eth_account import Account


@pytest.fixture(scope="module", autouse=True)
def zksync(is_zksync):
    if is_zksync:
        boa_zksync.set_zksync_test_env()
        for _public_key, private_key in EraTestNode.TEST_ACCOUNTS:
            boa.env.add_account(Account.from_key(private_key))
        boa.env.eoa = EraTestNode.TEST_ACCOUNTS[0][0]
