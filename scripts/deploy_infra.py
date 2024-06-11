# flake8: noqa E501

import os
import sys

import boa
import boa_zksync
import deployment_utils as deploy_utils
import yaml
from boa.network import NetworkEnv
from eth.codecs.abi.exceptions import DecodeError
from eth_account import Account
from eth_utils import keccak
from rich.console import Console as RichConsole

logger = RichConsole(file=sys.stdout)


def check_contract_deployed(network, designation):

    with open("./deployments.yaml", "r") as file:
        deployments = yaml.safe_load(file)

    if (
        network in deployments.keys()
        and designation in deployments[network].keys()
    ):
        return deployments[network][designation]


def store_deployed_contract(network, designation, deployment_address):

    with open("./deployments.yaml", "r") as file:
        deployments = yaml.safe_load(file)

    if not network in deployments.keys():
        deployments[network] = {}

    deployments[network][designation] = deployment_address

    with open("./deployments.yaml", "w") as file:
        yaml.dump(deployments, file)


def check_and_deploy(
    contract_obj,
    contract_designation,
    calculated_address,
    create2deployer,
    network,
    abi_encoded_args=b"",
    blueprint: bool = False,
    upkeep_deploy_log: bool = False,
):

    deployed_contract_address = check_contract_deployed(
        network, contract_designation
    )
    if deployed_contract_address:
        logger.log(f"Contract exists at {deployed_contract_address} ...")
        return contract_obj.at(deployed_contract_address)

    logger.log(f"Deploying {contract_designation} contract ...")
    try:
        salt = keccak(42069)
        compiled_bytecode = contract_obj.compiler_data.bytecode
        (
            precomputed_address,
            deployment_bytecode,
        ) = deploy_utils.get_create2_deployment_address(
            compiled_bytecode,
            abi_encoded_args,
            salt,
            create2deployer=create2deployer,
            blueprint=blueprint,
            blueprint_preamble=b"\xFE\x71\x00",
        )
        # assert precomputed_address == calculated_address

        deploy_utils.deploy_via_create2_factory(
            deployment_bytecode,
            salt,
            create2deployer=create2deployer,
        )
        deployed_address = precomputed_address

    except:

        logger.log(
            f"No create2deployer found for {network}. Deploying with CREATE."
        )
        if blueprint:
            if not "zksync" in network:
                c = contract_obj.deploy_as_blueprint()
            else:
                # we need special deployment code for zksync
                packed_precisions = 340282366920938463463374607431768211457
                packed_gamma_A = 136112946768375385385349842972852284582400000
                packed_fee_params = (
                    8847341539944400050877843276543133320576000000
                )
                packed_rebalancing_params = (
                    6125082604576892342340742933771827806226
                )
                c = contract_obj.deploy_as_blueprint(
                    "Blueprint",  # _name
                    "_",  # _symbol
                    ["0x0000000000000000000000000000000000000000"]
                    * 2,  # _coins
                    "0x0000000000000000000000000000000000000000",  # _math
                    b"\1" * 32,  # _salt
                    packed_precisions,
                    packed_gamma_A,
                    packed_fee_params,
                    packed_rebalancing_params,
                    1,  # initial_price
                )
        else:
            c = contract_obj.deploy()

        deployed_address = c.address

    logger.log(f"Deployed! At: {deployed_address}.")

    if upkeep_deploy_log:
        store_deployed_contract(
            network, contract_designation, str(deployed_address)
        )

    return contract_obj.at(deployed_address)


def deploy_infra(network, url, account, fork=False):

    logger.log(f"Deploying on {network} ...")
    contract_folder = "main"

    if network == "zksync:mainnet":
        contract_folder = "zksync"
        if not fork:
            boa_zksync.set_zksync_env(url)
            logger.log("Prodmode on zksync Era ...")
        else:
            boa_zksync.set_zksync_fork(url)
            logger.log("Forkmode on zksync Era ...")

        boa.env.set_eoa(Account.from_key(os.environ[account]))

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

    for _network, data in deploy_utils.curve_dao_network_settings.items():

        if _network in network:
            fee_receiver = data.fee_receiver_address

    assert fee_receiver, f"Curve's DAO contracts may not be on {network}."

    # --------------------- Initialise contract objects ---------------------

    math_contract_obj = boa.load_partial(
        f"./contracts/{contract_folder}/CurveCryptoMathOptimized2.vy"
    )
    views_contract_obj = boa.load_partial(
        f"./contracts/{contract_folder}/CurveCryptoViews2Optimized.vy"
    )
    amm_contract_obj = boa.load_partial(
        f"./contracts/{contract_folder}/CurveTwocryptoOptimized.vy"
    )
    factory_contract_obj = boa.load_partial(
        f"./contracts/{contract_folder}/CurveTwocryptoFactory.vy"
    )

    # deploy non-blueprint contracts:
    math_contract = check_and_deploy(
        contract_obj=math_contract_obj,
        contract_designation="math",
        network=network,
        create2deployer=CREATE2DEPLOYER,
        calculated_address="0x2005995a71243be9FB995DaB4742327dc76564Df",
        upkeep_deploy_log=not fork,
    )
    views_contract = check_and_deploy(
        contract_obj=views_contract_obj,
        contract_designation="views",
        network=network,
        create2deployer=CREATE2DEPLOYER,
        calculated_address="0x07CdEBF81977E111B08C126DEFA07818d0045b80",
        upkeep_deploy_log=not fork,
    )

    # deploy blueprint:
    amm_blueprint = check_and_deploy(
        contract_obj=amm_contract_obj,
        contract_designation="amm",
        network=network,
        create2deployer=CREATE2DEPLOYER,
        calculated_address="0x04Fd6beC7D45EFA99a27D29FB94b55c56dD07223",
        blueprint=True,
        upkeep_deploy_log=not fork,
    )

    # Factory:
    factory = check_and_deploy(
        contract_obj=factory_contract_obj,
        contract_designation="factory",
        network=network,
        create2deployer=CREATE2DEPLOYER,
        calculated_address="0x98EE851a00abeE0d95D08cF4CA2BdCE32aeaAF7F",
        upkeep_deploy_log=not fork,
    )

    # initialise ownership addresses: this is so we can do create2
    # addresses across multiple chains (where args are different)
    if factory.admin() == "0x0000000000000000000000000000000000000000":
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

    if network == "ethereum:mainnet":
        gauge_impl = check_contract_deployed(network, "gauge")
        if factory.gauge_implementation() != gauge_impl:
            logger.log(f"Setting gauge implementation to {gauge_impl} ...")
            factory.set_gauge_implementation(gauge_impl)

    logger.log("Infra deployed!")


def main():

    forkmode = False
    deployer = "FIDDYDEPLOYER"
    network = "zksync:mainnet"
    rpc = "https://mainnet.era.zksync.io"
    deploy_infra(
        network=network,
        url=rpc,
        account=deployer,
        fork=forkmode,
    )


if __name__ == "__main__":
    main()
