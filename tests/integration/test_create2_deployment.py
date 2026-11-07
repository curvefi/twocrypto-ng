"""Mainnet-fork rehearsal of the v2.2.0 implementation upgrade.

The legacy factory and gauge stay as deployed. The new math, pool blueprint
and views are deployed through the CREATE2 deployer at their predicted
addresses, the factory admin points the factory at them (as the governance
vote will), and a pool deployed from the factory is exercised end to end.
Impersonating the admin proves the setters, not the vote route.
"""

import os

import boa
import pytest
from eth_utils import keccak

from tests.utils.legacy import (
    LEGACY_FACTORY,
    LEGACY_GAUGE,
    load_legacy_partial,
)

FORK_BLOCK = 26_359_143
CREATE2_DEPLOYER = "0x13b0D85CcB8bf860b6b79AF3029fCA081AE9beF2"
SALT = keccak(42069)
BLUEPRINT_PREAMBLE = b"\xFE\x71\x00"

FACTORY = "0x98EE851a00abeE0d95D08cF4CA2BdCE32aeaAF7F"
NEW_MATH = "0x1b9d527e203dCA6303730C97ADC3101E2aE31FBE"
NEW_AMM = "0x8a161Ad9ca4eA9fF5E477e4cf05ced616C025c07"
NEW_VIEWS = "0x6cFe8D0e1d3356575d141ecCdEfe7e89F8364A03"

CRVUSD = "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E"
CRV = "0xD533a949740bb3306d119CC777fa900bA034cd52"

POOL_PARAMS = {
    "A": 400000,
    "gamma": 72500000000000,
    "mid_fee": 26000000,
    "out_fee": 45000000,
    "fee_gamma": 230000000000000,
    "allowed_extra_profit": 2000000000000,
    "adjustment_step": 146000000000000,
    "ma_time": 866,
    "initial_price": 634800240283136736,  # CRV priced in crvUSD
}
# Equal value of crvUSD and CRV at the initial price.
DEPOSIT = [
    10_000 * 10**18,
    10_000 * 10**36 // POOL_PARAMS["initial_price"],
]


def blueprint_initcode(initcode):
    body = BLUEPRINT_PREAMBLE + initcode
    return (
        b"\x61"
        + len(body).to_bytes(2, "big")
        + b"\x3d\x81\x60\x0a\x3d\x39\xf3"
        + body
    )


@pytest.fixture(scope="module")
def forked_chain():
    rpc_url = os.getenv("RPC_ETHEREUM")
    assert (
        rpc_url is not None
    ), "Set RPC_ETHEREUM to an Ethereum mainnet archive endpoint"
    env = boa.Env()
    env.fork(url=rpc_url, block_identifier=FORK_BLOCK, deprecated=False)
    with boa.swap_env(env):
        yield


@pytest.fixture(scope="module")
def create2deployer(forked_chain):
    return boa.load_abi("abi/create2deployer.json").at(CREATE2_DEPLOYER)


@pytest.fixture(scope="module")
def new_artifacts(create2deployer):
    """Deploy math, views and the pool blueprint; return the expected code."""
    math = boa.load_partial("contracts/main/CurveCryptoMathOptimized2.vy")
    views = boa.load_partial("contracts/main/CurveCryptoViews2Optimized.vy")
    amm = boa.load_partial("contracts/main/CurveTwocryptoOptimized.vy")
    artifacts = {
        NEW_MATH: (
            math.compiler_data.bytecode,
            math.compiler_data.bytecode_runtime,
        ),
        NEW_VIEWS: (
            views.compiler_data.bytecode,
            views.compiler_data.bytecode_runtime,
        ),
        NEW_AMM: (
            blueprint_initcode(amm.compiler_data.bytecode),
            BLUEPRINT_PREAMBLE + amm.compiler_data.bytecode,
        ),
    }
    for expected_address, (initcode, _) in artifacts.items():
        assert (
            create2deployer.computeAddress(SALT, keccak(initcode))
            == expected_address
        )
        assert boa.env.get_code(expected_address) == b""
        create2deployer.deploy(0, SALT, initcode)
    return artifacts


@pytest.fixture(scope="module")
def legacy_factory(forked_chain):
    return load_legacy_partial(LEGACY_FACTORY).at(FACTORY)


@pytest.fixture(scope="module")
def upgraded_factory(legacy_factory, new_artifacts):
    # Math before the blueprint: deploy_pool reads both pointers.
    with boa.env.prank(legacy_factory.admin()):
        legacy_factory.set_math_implementation(NEW_MATH)
        legacy_factory.set_pool_implementation(NEW_AMM, 0)
        legacy_factory.set_views_implementation(NEW_VIEWS)
    return legacy_factory


@pytest.fixture(scope="module")
def coins(forked_chain):
    erc20 = boa.load_partial("contracts/mocks/ERC20Mock.vy")
    return [erc20.at(CRVUSD), erc20.at(CRV)]


@pytest.fixture(scope="module")
def pool(upgraded_factory, coins, amm_interface):
    p = POOL_PARAMS
    with boa.env.prank(boa.env.generate_address()):
        address = upgraded_factory.deploy_pool(
            "Curve.fi crvUSD<>CRV",
            "crvUSD<>CRV",
            [coin.address for coin in coins],
            0,
            p["A"],
            p["gamma"],
            p["mid_fee"],
            p["out_fee"],
            p["fee_gamma"],
            p["allowed_extra_profit"],
            p["adjustment_step"],
            p["ma_time"],
            p["initial_price"],
        )
    return amm_interface.at(address)


@pytest.fixture(scope="module")
def user(pool, coins):
    account = boa.env.generate_address()
    for coin in coins:
        boa.deal(coin, account, 10**24)
        with boa.env.prank(account):
            coin.approve(pool, 2**256 - 1)
    return account


def test_legacy_factory_source_matches_deployed(
    legacy_factory, create2deployer
):
    factory = load_legacy_partial(LEGACY_FACTORY)
    assert (
        create2deployer.computeAddress(SALT, keccak(factory.bytecode))
        == FACTORY
    )
    assert boa.env.get_code(FACTORY) == factory.bytecode_runtime


def test_new_artifacts_deployed_with_expected_code(new_artifacts):
    for address, (_, expected_code) in new_artifacts.items():
        assert boa.env.get_code(address) == expected_code


def test_factory_points_at_new_implementations(upgraded_factory):
    assert upgraded_factory.math_implementation() == NEW_MATH
    assert upgraded_factory.pool_implementations(0) == NEW_AMM
    assert upgraded_factory.views_implementation() == NEW_VIEWS


def test_new_pool_bindings(pool, upgraded_factory):
    assert pool.MATH() == NEW_MATH
    assert pool.factory() == upgraded_factory.address
    assert pool.version() == "v2.2.0"
    assert pool.A() == POOL_PARAMS["A"]
    assert pool.gamma() == POOL_PARAMS["gamma"]


def test_pool_operations(pool, coins, user):
    with boa.env.prank(user):
        lp = pool.add_liquidity(DEPOSIT, 0)
        assert lp > 0

        dx = 100 * 10**18
        quoted = pool.get_dy(0, 1, dx)  # served by the new views contract
        assert pool.exchange(0, 1, dx, 0) == quoted > 0

        # The withdrawal claims admin fees first; the quote leaves that out.
        before = coins[1].balanceOf(user)
        quoted = pool.calc_withdraw_one_coin(lp // 100, 1)
        out = pool.remove_liquidity_one_coin(lp // 100, 1, 0)
        assert coins[1].balanceOf(user) - before == out
        assert quoted - quoted // 10000 < out <= quoted

        before = [coin.balanceOf(user) for coin in coins]
        pool.remove_liquidity(lp // 10, [0, 0])
        assert all(coin.balanceOf(user) > b for coin, b in zip(coins, before))


def test_legacy_gauge_with_new_pool(pool, upgraded_factory, user):
    gauge = load_legacy_partial(LEGACY_GAUGE).at(
        upgraded_factory.deploy_gauge(pool)
    )
    assert gauge.lp_token() == pool.address
    # Each test starts from the fixture state, so add liquidity here.
    with boa.env.prank(user):
        amount = pool.add_liquidity(DEPOSIT, 0) // 2
        assert amount > 0
        pool.approve(gauge, amount)
        gauge.deposit(amount)
    assert gauge.balanceOf(user) == amount
