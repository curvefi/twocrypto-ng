from shutil import which

import pytest
from boa_zksync.util import install_era_test_node, install_zkvyper_compiler

pytest_plugins = [
    "tests.fixtures.accounts",
    "tests.fixtures.tokens",
    "tests.fixtures.functions",
    "tests.fixtures.pool",
    "tests.fixtures.factory",
]


@pytest.fixture(scope="session")
def is_zksync():
    if not which("zkvyper"):
        install_zkvyper_compiler()
    if not which("era_test_node"):
        install_era_test_node()
    return True
