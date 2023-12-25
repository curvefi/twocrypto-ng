# flake8: noqa E501

import os
import sys

import boa
import deployment_utils as deploy_utils
from boa.network import NetworkEnv
from eth_account import Account
from eth_utils import keccak
from rich.console import Console as RichConsole

logger = RichConsole(file=sys.stdout)

deployments = {
    # Ethereum
    "ethereum:mainnet": {
        "math": "",
        "views": "",
        "amm": "",
        "factory": "",
        "gauge": "0x38D9BdA812da2C68dFC6aDE85A7F7a54E77F8325",
    },
    "ethereum:sepolia": {
        "math": "",
        "views": "",
        "amm": "",
        "factory": "",
    },
    # Layer 2
    "arbitrum:mainnet": {
        "math": "",
        "views": "",
        "amm": "",
        "factory": "",
    },
    "optimism:mainnet": {
        "math": "",
        "views": "",
        "amm": "",
        "factory": "",
    },
    "base:mainnet": {
        "math": "",
        "views": "",
        "amm": "",
        "factory": "",
    },
    "linea:mainnet": {
        "math": "",
        "views": "",
        "amm": "",
        "factory": "",
    },
    "scroll:mainnet": {
        "math": "",
        "views": "",
        "amm": "",
        "factory": "",
    },
    "pzkevm:mainnet": {
        "math": "",
        "views": "",
        "amm": "",
        "factory": "",
    },
    # Layer 1
    "gnosis:mainnet": {
        "math": "",
        "views": "",
        "amm": "",
        "factory": "",
    },
    "polygon:mainnet": {
        "math": "",
        "views": "",
        "amm": "",
        "factory": "",
    },
    "avax:mainnet": {
        "math": "",
        "views": "",
        "amm": "",
        "factory": "",
    },
    "ftm:mainnet": {
        "math": "",
        "views": "",
        "amm": "",
        "factory": "",
    },
    "bsc:mainnet": {
        "math": "",
        "views": "",
        "amm": "",
        "factory": "",
    },
    "celo:mainnet": {
        "math": "",
        "views": "",
        "amm": "",
        "factory": "",
    },
    "kava:mainnet": {
        "math": "",
        "views": "",
        "amm": "",
        "factory": "",
    },
    "aurora:mainnet": {
        "math": "",
        "views": "",
        "amm": "",
        "factory": "",
    },
    "mantle:mainnet": {
        "math": "",
        "views": "",
        "amm": "",
        "factory": "",
        "factory_ctor": "",  # noqa:E501
    },
}


def check_and_deploy(
    contract_obj,
    contract_designation,
    calculated_address,
    network,
    abi_encoded_args=b"",
    blueprint: bool = False,
):

    deployed_contract = deployments[network][contract_designation]

    if not deployed_contract:

        logger.log(f"Deploying {contract_designation} contract ...")
        salt = keccak(42069)
        compiled_bytecode = contract_obj.compiler_data.bytecode
        (
            precomputed_address,
            deployment_bytecode,
        ) = deploy_utils.get_create2_deployment_address(
            compiled_bytecode,
            abi_encoded_args,
            salt,
            blueprint=blueprint,
            blueprint_preamble=b"\xFE\x71\x00",
        )
        assert precomputed_address == calculated_address

        deploy_utils.deploy_via_create2_factory(deployment_bytecode, salt)
        contract = contract_obj.at(precomputed_address)
        logger.log(f"Deployed! At: {precomputed_address}.")

    else:

        logger.log(
            f"Deployed {contract_designation} contract exists. Using {deployed_contract} ..."
        )
        contract = contract_obj.at(deployed_contract)

    return contract


def deploy_infra(network, url, account, fork=False):

    logger.log(f"Deploying on {network} ...")

    if fork:
        boa.env.fork(url)
        logger.log("Forkmode ...")
        boa.env.eoa = deploy_utils.FIDDYDEPLOYER  # set eoa address here
    else:
        logger.log("Prodmode ...")
        boa.set_env(NetworkEnv(url))
        boa.env.add_account(Account.from_key(os.environ[account]))

    for _network, data in deploy_utils.curve_dao_network_settings.items():

        if _network in network:
            fee_receiver = data.fee_receiver_address

    assert fee_receiver, f"Curve's DAO contracts may not be on {network}."

    # --------------------- Initialise contract objects ---------------------

    math_contract_obj = boa.load_partial(
        "./contracts/main/CurveCryptoMathOptimized2.vy"
    )
    views_contract_obj = boa.load_partial(
        "./contracts/main/CurveCryptoViews2Optimized.vy"
    )
    amm_contract_obj = boa.load_partial(
        "./contracts/main/CurveTwocryptoOptimized.vy"
    )
    factory_contract_obj = boa.load_partial(
        "./contracts/main/CurveTwocryptoFactory.vy"
    )

    # deploy non-blueprint contracts:
    math_contract = check_and_deploy(
        contract_obj=math_contract_obj,
        contract_designation="math",
        network=network,
        calculated_address="0x2005995a71243be9FB995DaB4742327dc76564Df",
    )
    views_contract = check_and_deploy(
        contract_obj=views_contract_obj,
        contract_designation="views",
        network=network,
        calculated_address="0x07CdEBF81977E111B08C126DEFA07818d0045b80",
    )

    # deploy blueprint:
    amm_blueprint = check_and_deploy(
        contract_obj=amm_contract_obj,
        contract_designation="amm",
        network=network,
        calculated_address="0x04Fd6beC7D45EFA99a27D29FB94b55c56dD07223",
        blueprint=True,
    )

    # Factory:
    factory = check_and_deploy(
        contract_obj=factory_contract_obj,
        contract_designation="factory",
        network=network,
        calculated_address="0x98EE851a00abeE0d95D08cF4CA2BdCE32aeaAF7F",
    )

    # initialise ownership addresses: this is so we can do create2
    # addresses across multiple chains (where args are different)
    logger.log("Instantiating ownership ...")
    factory.initialise_ownership(fee_receiver, deploy_utils.FIDDYDEPLOYER)

    # Set up implementation addresses in the factory.
    if not factory.pool_implementations(0) == amm_blueprint.address:
        logger.log("Setting AMM implementation ...")
        factory.set_pool_implementation(amm_blueprint, 0)

    if not factory.views_implementation() == views_contract.address:
        logger.log("Setting Views implementation ...")
        factory.set_views_implementation(views_contract)

    if not factory.math_implementation() == math_contract.address:
        logger.log("Setting Math implementation ...")
        factory.set_math_implementation(math_contract)

    if (
        network == "ethereum:mainnet"
        and not factory.gauge_implementation() == deployments[network]["gauge"]
    ):
        gauge_impl = deployments[network]["gauge"]
        logger.log(f"Setting gauge implementation to {gauge_impl} ...")
        factory.set_gauge_implementation(gauge_impl)

    logger.log("Infra deployed!")


def main():

    forkmode = True
    deploy_infra(
        "ethereum:mainnet",
        os.environ["RPC_ETHEREUM"],
        "FIDDYDEPLOYER",
        fork=forkmode,
    )


if __name__ == "__main__":
    main()
