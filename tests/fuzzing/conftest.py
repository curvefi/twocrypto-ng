import boa
import pytest

from tests.utils.constants import MATH_DEPLOYER


@pytest.fixture(scope="module")
def math_optimized(deployer):
    with boa.env.prank(deployer):
        return MATH_DEPLOYER.deploy()


@pytest.fixture(scope="module")
def math_unoptimized(deployer):
    with boa.env.prank(deployer):
        return boa.load("contracts/old/CurveCryptoSwap2Math.vy")
