# flake8: noqa E501

import os
import sys

import boa
import deployment_utils as deploy_utils
from boa.network import NetworkEnv
from eth_abi import encode
from eth_account import Account
from rich.console import Console as RichConsole

logger = RichConsole(file=sys.stdout)

deployments = {
    # Ethereum
    "ethereum:mainnet": {
        "math": "",
        "views": "",
        "plain_amm": "",
        "meta_amm": "",
        "factory": "",
        "gauge": "",
    },
    "ethereum:sepolia": {
        "math": "",
        "views": "",
        "plain_amm": "",
        "meta_amm": "",
        "factory": "",
    },
    # Layer 2
    "arbitrum:mainnet": {
        "math": "",
        "views": "",
        "plain_amm": "",
        "meta_amm": "",
        "factory": "",
    },
    "optimism:mainnet": {
        "math": "",
        "views": "",
        "plain_amm": "",
        "meta_amm": "",
        "factory": "",
    },
    "base:mainnet": {
        "math": "",
        "views": "",
        "plain_amm": "",
        "meta_amm": "",
        "factory": "",
    },
    "linea:mainnet": {
        "math": "",
        "views": "",
        "plain_amm": "",
        "meta_amm": "",
        "factory": "",
    },
    "scroll:mainnet": {
        "math": "",
        "views": "",
        "plain_amm": "",
        "meta_amm": "",
        "factory": "",
    },
    "pzkevm:mainnet": {
        "math": "",
        "views": "",
        "plain_amm": "",
        "meta_amm": "",
        "factory": "",
    },
    # Layer 1
    "gnosis:mainnet": {
        "math": "",
        "views": "",
        "plain_amm": "",
        "meta_amm": "",
        "factory": "",
    },
    "polygon:mainnet": {
        "math": "",
        "views": "",
        "plain_amm": "",
        "meta_amm": "",
        "factory": "",
    },
    "avax:mainnet": {
        "math": "",
        "views": "",
        "plain_amm": "",
        "meta_amm": "",
        "factory": "",
    },
    "ftm:mainnet": {
        "math": "",
        "views": "",
        "plain_amm": "",
        "meta_amm": "",
        "factory": "",
    },
    "bsc:mainnet": {
        "math": "",
        "views": "",
        "plain_amm": "",
        "meta_amm": "",
        "factory": "",
    },
    "celo:mainnet": {
        "math": "",
        "views": "",
        "plain_amm": "",
        "meta_amm": "",
        "factory": "",
    },
    "kava:mainnet": {
        "math": "",
        "views": "",
        "plain_amm": "",
        "meta_amm": "",
        "factory": "",
    },
    "aurora:mainnet": {
        "math": "",
        "views": "",
        "plain_amm": "",
        "meta_amm": "",
        "factory": "",
    },
    "mantle:mainnet": {
        "math": "",
        "views": "",
        "plain_amm": "",
        "meta_amm": "",
        "factory": "",
        "factory_ctor": "",  # noqa:E501
    },
}


def check_and_deploy(
    contract_obj,
    contract_designation,
    network,
    blueprint: bool = False,
    args=[],
):

    deployed_contract = deployments[network][contract_designation]

    if not deployed_contract:
        logger.log(f"Deploying {contract_designation} contract ...")
        if not blueprint:
            contract = contract_obj.deploy(*args)
            if args:
                constructor_args = encode(["address", "address"], args)
                logger.log(
                    f"Constructor arguments for {contract_designation}: {constructor_args.hex()}"
                )
        else:
            contract = contract_obj.deploy_as_blueprint()
        logger.log(f"Deployed! At: {contract.address}.")
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

            owner = data.dao_ownership_contract
            fee_receiver = data.fee_receiver_address

    assert owner, f"Curve's DAO contracts may not be on {network}."
    assert fee_receiver, f"Curve's DAO contracts may not be on {network}."

    # --------------------- Deploy math, views, blueprints ---------------------

    assert NotImplementedError


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
