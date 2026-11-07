# flake8: noqa E501

import argparse
import os
import sys

# Resolve deployment_utils however the script is started (path or -m).
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import boa
import deployment_utils as deploy_utils
import yaml
from boa.network import NetworkEnv
from eth_account import Account
from eth_utils import keccak
from rich.console import Console as RichConsole

logger = RichConsole(file=sys.stdout)

CREATE2DEPLOYER_ADDRESS = "0x13b0D85CcB8bf860b6b79AF3029fCA081AE9beF2"
SALT = keccak(42069)

# CREATE2 addresses of the current sources: v2.2.0 implementations (Vyper 0.4.3) and the
# legacy factory (Vyper 0.3.10). They are the same on every chain with the deployer above.
MATH_ADDRESS = "0x1b9d527e203dCA6303730C97ADC3101E2aE31FBE"
AMM_ADDRESS = "0x8a161Ad9ca4eA9fF5E477e4cf05ced616C025c07"
VIEWS_ADDRESS = "0x6cFe8D0e1d3356575d141ecCdEfe7e89F8364A03"
FACTORY_ADDRESS = "0x98EE851a00abeE0d95D08cF4CA2BdCE32aeaAF7F"


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


def connect(url, account, fork=False):

    if fork:
        boa.env.fork(url)
        logger.log("Forkmode ...")
        boa.env.eoa = deploy_utils.FIDDYDEPLOYER  # set eoa address here
    else:
        logger.log("Prodmode ...")
        boa.set_env(NetworkEnv(url))
        boa.env.add_account(Account.from_key(os.environ[account]))


def get_create2deployer():

    assert boa.env.get_code(
        CREATE2DEPLOYER_ADDRESS
    ), f"No CREATE2 deployer at {CREATE2DEPLOYER_ADDRESS} on this chain."
    return boa.load_abi("abi/create2deployer.json").at(CREATE2DEPLOYER_ADDRESS)


def initcode(contract_obj):
    # Vyper 0.4.3 sources load as VyperDeployer; the legacy 0.3.10 factory and
    # gauge load through vvm as VVMDeployer, which only exposes `.bytecode`.
    compiler_data = getattr(contract_obj, "compiler_data", None)
    if compiler_data is not None:
        return compiler_data.bytecode
    return contract_obj.bytecode


def expected_code(contract_obj, blueprint):
    if blueprint:
        return b"\xFE\x71\x00" + initcode(contract_obj)
    compiler_data = getattr(contract_obj, "compiler_data", None)
    if compiler_data is not None:
        return compiler_data.bytecode_runtime
    return (
        contract_obj.bytecode_runtime
    )  # set by deploy_utils.load_legacy_partial


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

    (
        precomputed_address,
        deployment_bytecode,
    ) = deploy_utils.get_create2_deployment_address(
        initcode(contract_obj),
        abi_encoded_args,
        SALT,
        create2deployer=create2deployer,
        blueprint=blueprint,
        blueprint_preamble=b"\xFE\x71\x00",
    )
    assert precomputed_address == calculated_address, (
        f"{contract_designation}: this build deploys to {precomputed_address}, "
        f"expected {calculated_address}."
    )

    recorded_address = check_contract_deployed(network, contract_designation)
    assert (
        recorded_address is None or recorded_address == precomputed_address
    ), (
        f"{contract_designation}: deployments.yaml records {recorded_address} for "
        f"{network}, not {precomputed_address}; archive the old entry first."
    )

    if boa.env.get_code(precomputed_address):
        logger.log(
            f"{contract_designation} exists at {precomputed_address} ..."
        )
    else:
        logger.log(f"Deploying {contract_designation} contract ...")
        deploy_utils.deploy_via_create2_factory(
            deployment_bytecode,
            SALT,
            create2deployer=create2deployer,
        )
        logger.log(f"Deployed! At: {precomputed_address}.")

    assert boa.env.get_code(precomputed_address) == expected_code(
        contract_obj, blueprint
    ), f"{contract_designation}: code at {precomputed_address} is not this build."

    if upkeep_deploy_log:
        store_deployed_contract(
            network, contract_designation, str(precomputed_address)
        )

    return contract_obj.at(precomputed_address)


def deploy_infra(network, url, account, fork=False):

    logger.log(f"Deploying on {network} ...")
    connect(url, account, fork)
    CREATE2DEPLOYER = get_create2deployer()

    fee_receiver = None
    for _network, data in deploy_utils.curve_dao_network_settings.items():

        if _network in network:
            fee_receiver = data.fee_receiver_address

    assert fee_receiver, f"Curve's DAO contracts may not be on {network}."

    # Base, Kava and X Layer use deploy_implementation_and_update.py instead.
    recorded_factory = check_contract_deployed(network, "factory")
    assert recorded_factory in (None, FACTORY_ADDRESS), recorded_factory

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
    factory_contract_obj = deploy_utils.load_legacy_partial(
        deploy_utils.LEGACY_FACTORY
    )

    # deploy non-blueprint contracts:
    math_contract = check_and_deploy(
        contract_obj=math_contract_obj,
        contract_designation="math",
        network=network,
        create2deployer=CREATE2DEPLOYER,
        calculated_address=MATH_ADDRESS,
        upkeep_deploy_log=not fork,
    )
    views_contract = check_and_deploy(
        contract_obj=views_contract_obj,
        contract_designation="views",
        network=network,
        create2deployer=CREATE2DEPLOYER,
        calculated_address=VIEWS_ADDRESS,
        upkeep_deploy_log=not fork,
    )

    # deploy blueprint:
    amm_blueprint = check_and_deploy(
        contract_obj=amm_contract_obj,
        contract_designation="amm",
        network=network,
        create2deployer=CREATE2DEPLOYER,
        calculated_address=AMM_ADDRESS,
        blueprint=True,
        upkeep_deploy_log=not fork,
    )

    # Factory:
    factory = check_and_deploy(
        contract_obj=factory_contract_obj,
        contract_designation="factory",
        network=network,
        create2deployer=CREATE2DEPLOYER,
        calculated_address=FACTORY_ADDRESS,
    )

    # initialise ownership addresses: this is so we can do create2
    # addresses across multiple chains (where args are different)
    if factory.admin() == "0x0000000000000000000000000000000000000000":
        logger.log("Instantiating ownership ...")
        factory.initialise_ownership(fee_receiver, boa.env.eoa)

    # Whoever deployed the factory first owns it: check before recording it.
    assert factory.admin() == boa.env.eoa
    assert factory.fee_receiver().lower() == fee_receiver.lower()

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

    if not fork:
        store_deployed_contract(network, "factory", str(factory.address))
    logger.log("Infra deployed!")


def main():

    parser = argparse.ArgumentParser(
        description="Deploy the twocrypto-ng factory and implementations on a chain."
    )
    parser.add_argument(
        "--network", required=True, help='e.g. "arbitrum:mainnet"'
    )
    parser.add_argument("--url", required=True, help="RPC endpoint")
    parser.add_argument(
        "--account",
        default="FIDDYDEPLOYER",
        help="environment variable holding the deployer private key",
    )
    parser.add_argument(
        "--fork", action="store_true", help="run on a local fork"
    )
    args = parser.parse_args()

    deploy_infra(
        network=args.network,
        url=args.url,
        account=args.account,
        fork=args.fork,
    )


if __name__ == "__main__":
    main()
