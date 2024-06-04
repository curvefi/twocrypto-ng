# flake8: noqa E501

import os
import sys

import boa
import deployment_utils as deploy_utils
import yaml
from boa.network import NetworkEnv
from eth_account import Account
from rich.console import Console as RichConsole

sys.path.append("./")
from scripts.deploy_infra import check_and_deploy

logger = RichConsole(file=sys.stdout)


def fetch_url(network):
    return os.getenv("DRPC_URL") % (network, os.getenv("DRPC_KEY"))


def deploy(network, url, account, fork=False):

    logger.log(f"Deploying on {network} ...")

    if not url:
        url = fetch_url(network.split(":")[0])

    if fork:
        boa.env.fork(url)
        logger.log("Forkmode ...")
        boa.env.eoa = deploy_utils.FIDDYDEPLOYER  # set eoa address here
    else:
        logger.log("Prodmode ...")
        boa.set_env(NetworkEnv(url))
        boa.env.add_account(Account.from_key(os.environ[account]))

    CREATE2DEPLOYER = boa.load_abi("abi/create2deployer.json").at(
        "0x13b0D85CcB8bf860b6b79AF3029fCA081AE9beF2"
    )

    with open("./deployments.yaml", "r") as file:
        deployments = yaml.safe_load(file)

    factory = boa.load_partial("./contracts/main/CurveTwocryptoFactory.vy").at(
        deployments[network]["factory"]
    )

    math_contract_obj = boa.load_partial(
        "./contracts/main/CurveCryptoMathOptimized2.vy"
    )
    amm_contract_obj = boa.load_partial(
        "./contracts/main/CurveTwocryptoOptimized.vy"
    )

    math_contract = check_and_deploy(
        contract_obj=math_contract_obj,
        contract_designation="math",
        network=network,
        create2deployer=CREATE2DEPLOYER,
        calculated_address="0x1Fd8Af16DC4BEBd950521308D55d0543b6cDF4A1",
        upkeep_deploy_log=not fork,
    )

    amm_blueprint = check_and_deploy(
        contract_obj=amm_contract_obj,
        contract_designation="amm",
        network=network,
        create2deployer=CREATE2DEPLOYER,
        calculated_address="0x934791f7F391727db92BFF94cd789c4623d14c52",
        blueprint=True,
        upkeep_deploy_log=not fork,
    )

    if boa.env.eoa == factory.admin():

        # update implementation here
        if not factory.pool_implementations(0) == amm_blueprint.address:
            logger.log("Setting AMM implementation ...")
            factory.set_pool_implementation(amm_blueprint, 0)

        if not factory.math_implementation() == math_contract.address:
            logger.log("Setting Math implementation ...")
            factory.set_math_implementation(math_contract)

        logger.log("Done!")

    else:

        logger.log(f"Could not update implementation for factory on {network}")


def main():

    forkmode = False
    deploy(
        network="arbitrum:mainnet",
        url="",
        account="FIDDYDEPLOYER",
        fork=forkmode,
    )


if __name__ == "__main__":
    main()
