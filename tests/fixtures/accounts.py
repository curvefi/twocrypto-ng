import boa
import pytest


@pytest.fixture(scope="module")
def deployer():
    return boa.env.generate_address()


@pytest.fixture(scope="module")
def owner():
    return boa.env.generate_address()


@pytest.fixture(scope="module")
def factory_admin(factory):
    return factory.admin()


@pytest.fixture(scope="module")
def fee_receiver():
    return boa.env.generate_address()


@pytest.fixture(scope="module")
def user():
    acc = boa.env.generate_address()
    boa.env.set_balance(acc, 10**25)
    return acc


@pytest.fixture(scope="module")
def user_b():
    acc = boa.env.generate_address()
    boa.env.set_balance(acc, 10**25)
    return acc


@pytest.fixture(scope="module")
def users():
    accs = [i() for i in [boa.env.generate_address] * 10]
    for acc in accs:
        boa.env.set_balance(acc, 10**25)
    return accs


@pytest.fixture(scope="module")
def alice():
    acc = boa.env.generate_address()
    boa.env.set_balance(acc, 10**25)
    return acc


@pytest.fixture(scope="module")
def loaded_alice(swap, alice):
    boa.deal(swap, alice, 10**21)
    return alice


@pytest.fixture(scope="module")
def bob():
    acc = boa.env.generate_address()
    boa.env.set_balance(acc, 10**25)
    return acc


@pytest.fixture(scope="module")
def charlie():
    acc = boa.env.generate_address()
    boa.env.set_balance(acc, 10**25)
    return acc
