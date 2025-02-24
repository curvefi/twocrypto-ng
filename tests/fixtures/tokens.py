import boa
import pytest


@pytest.fixture(scope="module")
def usd(deployer):
    with boa.env.prank(deployer):
        return boa.load("tests/mocks/MockERC20.vy", "USD", "USD", 18)


@pytest.fixture(scope="module")
def btc(deployer):
    with boa.env.prank(deployer):
        return boa.load("tests/mocks/MockERC20.vy", "BTC", "BTC", 18)


@pytest.fixture(scope="module")
def stg(deployer):
    with boa.env.prank(deployer):
        return boa.load("tests/mocks/MockERC20.vy", "STG", "STG", 18)


@pytest.fixture(scope="module")
def usdt(deployer):
    with boa.env.prank(deployer):
        return boa.load("tests/mocks/MockERC20.vy", "USDT", "USDT", 6)


@pytest.fixture(scope="module")
def usdc(deployer):
    with boa.env.prank(deployer):
        return boa.load("tests/mocks/MockERC20.vy", "USDC", "USDC", 6)


@pytest.fixture(scope="module")
def dai(deployer):
    with boa.env.prank(deployer):
        return boa.load("tests/mocks/MockERC20.vy", "DAI", "DAI", 18)


@pytest.fixture(scope="module")
def coins(usd, weth):
    yield [usd, weth]


@pytest.fixture(scope="module")
def stgusdc(stg, usdc):
    yield [stg, usdc]


@pytest.fixture(scope="module")
def stablecoins(usdc, usdt, dai):
    yield [dai, usdc, usdt]


@pytest.fixture(scope="module")
def pool_coins(coins):
    yield coins
