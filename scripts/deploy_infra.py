# flake8: noqa E501
import os
import sys
import boa
import boa_zksync
import deployment_utils as deploy_utils
import yaml
from boa.network import NetworkEnv
from eth_account import Account
from eth_utils import keccak
from rich.console import Console as RichConsole

# Professional logging via Rich for better DX (Developer Experience)
logger = RichConsole(file=sys.stdout)

/**
 * Registry Management
 * These functions handle 'deployments.yaml' to ensure idempotency.
 * If a script fails halfway, it knows exactly which contracts were already deployed.
 */
def check_contract_deployed(network, designation):
    with open("./deployments.yaml", "r") as file:
        deployments = yaml.safe_load(file)
    return deployments.get(network, {}).get(designation)

[Image of Smart Contract Deployment Registry Workflow]

/**
 * check_and_deploy
 * Optimized for CREATE2: Attempts to deploy at a precomputed address.
 * Falls back to standard CREATE if no deployer factory is found.
 */
def check_and_deploy(contract_obj, contract_designation, calculated_address, create2deployer, network, ...):
    # Idempotency check: Skip if already registered
    deployed_address = check_contract_deployed(network, contract_designation)
    if deployed_address:
        logger.log(f"Found {contract_designation} at {deployed_address}")
        return contract_obj.at(deployed_address)

    try:
        # Precomputing address for cross-chain consistency
        salt = keccak(42069)
        precomputed, bytecode = deploy_utils.get_create2_deployment_address(...)
        deploy_utils.deploy_via_create2_factory(bytecode, salt, create2deployer=create2deployer)
        deployed_address = precomputed
    except:
        # Fallback for chains without CREATE2 Factory (or local forks)
        c = contract_obj.deploy_as_blueprint() if blueprint else contract_obj.deploy()
        deployed_address = c.address

    # Store result for future runs
    if upkeep_deploy_log:
        store_deployed_contract(network, contract_designation, str(deployed_address))
    return contract_obj.at(deployed_address)

[Image of CREATE2 vs CREATE opcode deployment logic]

/**
 * deploy_infra
 * Orchestrates the deployment of Curve Crypto (Twocrypto) V2 Factory and its dependencies.
 */
def deploy_infra(network, url, account, fork=False):
    # --- Environment Setup ---
    # Specific handling for zkSync Era (different bytecode/env)
    if "zksync" in network:
        if not fork: boa_zksync.set_zksync_env(url)
        else: boa_zksync.set_zksync_fork(url)
    else:
        if fork: boa.env.fork(url)
        else: boa.set_env(NetworkEnv(url))

    # --- Deploying Core Components ---
    # 1. Math: Optimized mathematical primitives for crypto pools
    # 2. Views: Calculation of prices, balances, and slippage
    # 3. Blueprint (AMM): The template used by the Factory to spawn new pools
    # 4. Factory: The registry and deployment manager
    
    # Logic for instantiating ownership and setting implementations follows...
    # (Factory setup connects Math, Views, and AMM templates)

[Image of Curve Finance Twocrypto V2 Factory Architecture]
