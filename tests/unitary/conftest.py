import boa
import boa_zksync
import pytest


@pytest.fixture(scope="module", autouse=True)
def zksync(deployer):
    boa_zksync.set_zksync_test_env()
    boa.interpret.disable_cache()
