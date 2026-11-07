# flake8: noqa E501

import argparse
import contextlib
import os
import sys

import boa
import yaml
from rich.console import Console as RichConsole

sys.path.append("./")
from scripts.deploy_infra import (
    AMM_ADDRESS,
    MATH_ADDRESS,
    VIEWS_ADDRESS,
    check_and_deploy,
    connect,
    get_create2deployer,
)
from scripts.deployment_utils import LEGACY_FACTORY, load_legacy_partial

logger = RichConsole(file=sys.stdout)


def fetch_url(network):
    return os.getenv("DRPC_URL") % (network, os.getenv("DRPC_KEY"))


def deploy(network, url, account, fork=False):

    logger.log(f"Deploying on {network} ...")

    if not url:
        url = fetch_url(network.split(":")[0])

    connect(url, account, fork)
    CREATE2DEPLOYER = get_create2deployer()

    with open("./deployments.yaml", "r") as file:
        deployments = yaml.safe_load(file)

    factory = load_legacy_partial(LEGACY_FACTORY).at(
        deployments[network]["factory"]
    )

    math_contract = check_and_deploy(
        contract_obj=boa.load_partial(
            "./contracts/main/CurveCryptoMathOptimized2.vy"
        ),
        contract_designation="math",
        network=network,
        create2deployer=CREATE2DEPLOYER,
        calculated_address=MATH_ADDRESS,
        upkeep_deploy_log=not fork,
    )

    amm_blueprint = check_and_deploy(
        contract_obj=boa.load_partial(
            "./contracts/main/CurveTwocryptoOptimized.vy"
        ),
        contract_designation="amm",
        network=network,
        create2deployer=CREATE2DEPLOYER,
        calculated_address=AMM_ADDRESS,
        blueprint=True,
        upkeep_deploy_log=not fork,
    )

    views_contract = check_and_deploy(
        contract_obj=boa.load_partial(
            "./contracts/main/CurveCryptoViews2Optimized.vy"
        ),
        contract_designation="views",
        network=network,
        create2deployer=CREATE2DEPLOYER,
        calculated_address=VIEWS_ADDRESS,
        upkeep_deploy_log=not fork,
    )

    # Math before the pool blueprint: deploy_pool reads both pointers.
    updates = [
        (
            "set_math_implementation",
            (math_contract.address,),
            factory.math_implementation,
        ),
        (
            "set_pool_implementation",
            (amm_blueprint.address, 0),
            lambda: factory.pool_implementations(0),
        ),
        (
            "set_views_implementation",
            (views_contract.address,),
            factory.views_implementation,
        ),
    ]

    def pending():
        return [
            (name, args)
            for name, args, current in updates
            if current() != args[0]
        ]

    admin = factory.admin()
    if pending() and (fork or boa.env.eoa == admin):
        # In fork mode this impersonates the admin to rehearse the governance execution.
        sender = boa.env.prank(admin) if fork else contextlib.nullcontext()
        with sender:
            for name, args in pending():
                logger.log(f"Calling {name}{args} ...")
                getattr(factory, name)(*args)

    if pending():
        logger.log(f"Factory admin {admin} must execute on {factory.address}:")
        for name, args in pending():
            calldata = getattr(factory, name).prepare_calldata(*args)
            logger.log(f"  {name}{args}: 0x{calldata.hex()}")
        return

    logger.log(
        "Done! The factory points at the new math, pool blueprint and views."
    )


def main():

    parser = argparse.ArgumentParser(
        description="Deploy new implementations and point an existing factory at them."
    )
    parser.add_argument(
        "--network", required=True, help='e.g. "ethereum:mainnet"'
    )
    parser.add_argument(
        "--url",
        default="",
        help="RPC endpoint (default: DRPC_URL with DRPC_KEY)",
    )
    parser.add_argument(
        "--account",
        default="FIDDYDEPLOYER",
        help="environment variable holding the deployer private key",
    )
    parser.add_argument(
        "--fork", action="store_true", help="run on a local fork"
    )
    args = parser.parse_args()

    deploy(
        network=args.network,
        url=args.url,
        account=args.account,
        fork=args.fork,
    )


if __name__ == "__main__":
    main()
