import boa
import pytest
from boa_zksync import EraTestNode
from eth_account.account import Account

from tests.utils.tokens import mint_for_testing

_era_accounts = [Account.from_key(private_key)
                 for public_key, private_key in EraTestNode.TEST_ACCOUNTS]


@pytest.fixture(scope="module")
def deployer(is_zksync):
    if is_zksync:
        return EraTestNode.TEST_ACCOUNTS[0][0]
    return boa.env.generate_address()


@pytest.fixture(scope="module")
def owner(is_zksync):
    if is_zksync:
        return EraTestNode.TEST_ACCOUNTS[1][0]
    return boa.env.generate_address()


@pytest.fixture(scope="module")
def hacker(is_zksync):
    if is_zksync:
        return EraTestNode.TEST_ACCOUNTS[2][0]
    return boa.env.generate_address()


@pytest.fixture(scope="module")
def factory_admin(factory):
    return factory.admin()


@pytest.fixture(scope="module")
def fee_receiver(is_zksync):
    if is_zksync:
        return EraTestNode.TEST_ACCOUNTS[3][0]
    return boa.env.generate_address()


@pytest.fixture(scope="module")
def user(is_zksync):
    if is_zksync:
        return EraTestNode.TEST_ACCOUNTS[4][0]
    acc = boa.env.generate_address()
    boa.env.set_balance(acc, 10**25)
    return acc


@pytest.fixture(scope="module")
def user_b(is_zksync):
    if is_zksync:
        return EraTestNode.TEST_ACCOUNTS[5][0]
    acc = boa.env.generate_address()
    boa.env.set_balance(acc, 10**25)
    return acc


@pytest.fixture(scope="module")
def users():
    accs = [boa.env.generate_address() for _ in range(10)]
    for acc in accs:
        boa.env.set_balance(acc, 10**25)
    return accs


@pytest.fixture(scope="module")
def eth_acc():
    return Account.create()


@pytest.fixture(scope="module")
def alice(is_zksync):
    if is_zksync:
        return EraTestNode.TEST_ACCOUNTS[6][0]
    acc = boa.env.generate_address()
    boa.env.set_balance(acc, 10**25)
    return acc


@pytest.fixture(scope="module")
def loaded_alice(swap, alice):
    mint_for_testing(swap, alice, 10**21)
    return alice


@pytest.fixture(scope="module")
def bob(is_zksync):
    if is_zksync:
        return EraTestNode.TEST_ACCOUNTS[7][0]
    acc = boa.env.generate_address()
    boa.env.set_balance(acc, 10**25)
    return acc


@pytest.fixture(scope="module")
def charlie(is_zksync):
    if is_zksync:
        return EraTestNode.TEST_ACCOUNTS[8][0]
    acc = boa.env.generate_address()
    boa.env.set_balance(acc, 10**25)
    return acc
