import pytest

pytest_plugins = [
    "tests.fixtures.accounts",
    "tests.fixtures.tokens",
    "tests.fixtures.functions",
    "tests.fixtures.pool",
    "tests.fixtures.factory",
]


@pytest.fixture(scope="session")
def is_zksync():
    return True
