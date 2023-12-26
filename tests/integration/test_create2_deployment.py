import os

import boa
import pytest
from eth_utils import keccak


@pytest.fixture(scope="module")
def forked_chain():
    rpc_url = os.getenv("RPC_ETHEREUM")
    assert (
        rpc_url is not None
    ), "Provider url is not set, add RPC_ETHEREUM param to env"
    boa.env.fork(url=rpc_url)


@pytest.fixture(scope="module")
def create2deployer():
    return boa.load_abi("abi/create2deployer.json").at(
        "0x13b0D85CcB8bf860b6b79AF3029fCA081AE9beF2"
    )


def get_create2_deployment_address(
    create2deployer,
    compiled_bytecode,
    abi_encoded_ctor,
    salt,
    blueprint=False,
    blueprint_preamble=b"\xFE\x71\x00",
):
    deployment_bytecode = compiled_bytecode + abi_encoded_ctor
    if blueprint:
        # Add blueprint preamble to disable calling the contract:
        blueprint_bytecode = blueprint_preamble + deployment_bytecode
        # Add code for blueprint deployment:
        len_blueprint_bytecode = len(blueprint_bytecode).to_bytes(2, "big")
        deployment_bytecode = (
            b"\x61"
            + len_blueprint_bytecode
            + b"\x3d\x81\x60\x0a\x3d\x39\xf3"
            + blueprint_bytecode
        )

    return (
        create2deployer.computeAddress(salt, keccak(deployment_bytecode)),
        deployment_bytecode,
    )


def deploy_via_create2_factory(create2deployer, deployment_bytecode, salt):
    create2deployer.deploy(0, salt, deployment_bytecode)


def deploy_contract(
    contract_obj,
    abi_encoded_args,
    create2deployer,
    calculated_address,
    deployer=boa.env.generate_address(),
    blueprint: bool = False,
):

    salt = keccak(42069)
    compiled_bytecode = contract_obj.compiler_data.bytecode
    (
        precomputed_address,
        deployment_bytecode,
    ) = get_create2_deployment_address(
        create2deployer,
        compiled_bytecode,
        abi_encoded_args,
        salt,
        blueprint=blueprint,
        blueprint_preamble=b"\xFE\x71\x00",
    )
    assert precomputed_address == calculated_address

    with boa.env.prank(deployer):
        deploy_via_create2_factory(create2deployer, deployment_bytecode, salt)

    return contract_obj.at(precomputed_address)


@pytest.fixture(scope="module")
def math_contract(forked_chain, create2deployer):
    return deploy_contract(
        boa.load_partial("contracts/main/CurveCryptoMathOptimized2.vy"),
        abi_encoded_args=b"",
        create2deployer=create2deployer,
        calculated_address="0x2005995a71243be9FB995DaB4742327dc76564Df",
        blueprint=False,
    )


@pytest.fixture(scope="module")
def gauge_implementation(forked_chain, create2deployer):
    return deploy_contract(
        boa.load_partial("contracts/main/LiquidityGauge.vy"),
        abi_encoded_args=b"",
        create2deployer=create2deployer,
        calculated_address="0xF0B468653de6475c2d17c0b7b5405417CE6a6d67",
        blueprint=True,
    )


@pytest.fixture(scope="module")
def amm_implementation(forked_chain, create2deployer):
    return deploy_contract(
        boa.load_partial("contracts/main/CurveTwocryptoOptimized.vy"),
        abi_encoded_args=b"",
        create2deployer=create2deployer,
        calculated_address="0x04Fd6beC7D45EFA99a27D29FB94b55c56dD07223",
        blueprint=True,
    )


@pytest.fixture(scope="module")
def views_contract(forked_chain, create2deployer):
    return deploy_contract(
        boa.load_partial("contracts/main/CurveCryptoViews2Optimized.vy"),
        abi_encoded_args=b"",
        create2deployer=create2deployer,
        calculated_address="0x07CdEBF81977E111B08C126DEFA07818d0045b80",
        blueprint=False,
    )


@pytest.fixture(scope="module")
def factory(
    deployer,
    fee_receiver,
    owner,
    amm_implementation,
    gauge_implementation,
    views_contract,
    math_contract,
    forked_chain,
    create2deployer,
):

    _factory = deploy_contract(
        boa.load_partial("contracts/main/CurveTwocryptoFactory.vy"),
        abi_encoded_args=b"",
        create2deployer=create2deployer,
        calculated_address="0x98EE851a00abeE0d95D08cF4CA2BdCE32aeaAF7F",
        deployer=deployer,
        blueprint=False,
    )

    with boa.env.prank(deployer):
        _factory.initialise_ownership(fee_receiver, owner)

    with boa.env.prank(owner):
        _factory.set_pool_implementation(amm_implementation.address, 0)
        _factory.set_gauge_implementation(gauge_implementation.address)
        _factory.set_views_implementation(views_contract.address)
        _factory.set_math_implementation(math_contract.address)

    return _factory


@pytest.fixture(scope="module")
def coins():
    erc20_mock = boa.load_partial("./contracts/mocks/ERC20Mock.vy")
    return [
        erc20_mock.at("0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E"),
        erc20_mock.at("0xD533a949740bb3306d119CC777fa900bA034cd52"),
    ]


@pytest.fixture(scope="module")
def pool(coins, factory, amm_interface, deployer, forked_chain):
    _params = {
        "A": 400000,
        "gamma": 72500000000000,
        "mid_fee": 26000000,
        "out_fee": 45000000,
        "allowed_extra_profit": 2000000000000,
        "fee_gamma": 230000000000000,
        "adjustment_step": 146000000000000,
        "ma_time": 866,
        "initial_prices": 634800240283136736,
    }

    with boa.env.prank(deployer):
        swap = factory.deploy_pool(
            "Curve.fi crvUSD<>CRV",  # _name: String[64]
            "crvUSD<>CRV",  # _symbol: String[32]
            [coin.address for coin in coins],  # _coins: address[N_COINS]
            0,  # implementation_id: uint256
            _params["A"],  # A: uint256
            _params["gamma"],  # gamma: uint256
            _params["mid_fee"],  # mid_fee: uint256
            _params["out_fee"],  # out_fee: uint256
            _params["fee_gamma"],  # fee_gamma: uint256
            _params["allowed_extra_profit"],  # allowed_extra_profit: uint256
            _params["adjustment_step"],  # adjustment_step: uint256
            _params["ma_time"],  # ma_exp_time: uint256
            _params["initial_prices"],  # initial_price: uint256
        )

    return amm_interface.at(swap)


def test_A_gamma(pool, forked_chain):

    assert pool.A() == 400000
    assert pool.gamma() == 72500000000000
