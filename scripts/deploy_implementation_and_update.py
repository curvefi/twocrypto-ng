# flake8: noqa E501

import os
import sys

import boa
import deployment_utils as deploy_utils
import yaml
from boa.network import NetworkEnv
from eth_account import Account
from rich.console import Console as RichConsole

from scripts.deploy_infra import check_and_deploy

logger = RichConsole(file=sys.stdout)


def deploy_implementation(network, url, account, fork=False):

    logger.log(f"Deploying on {network} ...")

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
    
    factory = boa.load_partial("./contracts/main/CurveTwocryptoFactory.vy").at(deployments[network]['factory'])
    
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
        calculated_address="0x2005995a71243be9FB995DaB4742327dc76564Df",
        upkeep_deploy_log=not fork,
    )
    
    amm_blueprint = check_and_deploy(
        contract_obj=amm_contract_obj,
        contract_designation="amm",
        network=network,
        create2deployer=CREATE2DEPLOYER,
        calculated_address="0x04Fd6beC7D45EFA99a27D29FB94b55c56dD07223",
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

    forkmode = True
    deploy_implementation(
        network="",
        url="",
        account="",
        fork=forkmode,
    )


if __name__ == "__main__":
    main()