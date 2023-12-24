# flake8: noqa E501

import os
import sys

import boa
import deployment_utils as deploy_utils
from boa.network import NetworkEnv
from eth_abi import encode
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
    network,
    abi_encoded_args,
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

        contract = deploy_utils.deploy_via_create2_factory(
            deployment_bytecode, salt
        )

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
    math_contract = check_and_deploy(math_contract_obj, "math", network)
    views_contract = check_and_deploy(views_contract_obj, "views", network)

    # deploy blueprint:
    plain_blueprint = check_and_deploy(
        amm_contract_obj, "amm", network, blueprint=True
    )

    # Factory:
    args = [fee_receiver, deploy_utils.FIDDYDEPLOYER]
    factory = check_and_deploy(
        factory_contract_obj, "factory", network, False, args
    )

    # Set up implementation addresses in the factory:
    # This also checks if create2 deployment went well.
    factory.set_pool_implementation(plain_blueprint, 0)
    factory.set_views_implementation(views_contract)
    factory.set_math_implementation(math_contract)

    if network == "ethereum:mainnet":
        factory.set_gauge_implementation(deployments[network]["gauge"])


def main():

    forkmode = True

    deploy_infra(
        "gnosis:mainnet",
        os.environ["RPC_GNOSIS"],
        "FIDDYDEPLOYER",
        fork=forkmode,
    )


if __name__ == "__main__":
    main()
