import os

import boa
from boa.explorer import Etherscan
from eth_account import Account
from secure_key_utils import decrypt_private_key, getpass


# Deployment configuration. Relative controls are WADs: 1e18 = 100%.
DRPC_API_KEY = os.environ.get("DRPC_API_KEY")
ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY")
RPC_URL = f"https://lb.drpc.org/ogrpc?network=eth&dkey={DRPC_API_KEY}"
EXPECTED_CHAIN_ID = 1
WAD = 10**18

POOL = "0x313698667d7FDD6789a9BC70821309ff891E729A"  # Set the target pool.
POLICY_ADDRESS = ""
FAST_HALF_LIFE = 7_500  # seconds
SLOW_HALF_LIFE = 54_000  # seconds
KAPPA = int(WAD * 1.27)
DEADBAND = int(WAD * 2.8 / 10_000)  # bps
MIN_CAP = int(WAD * 12 / 10_000)  # bps
MAX_CAP = int(WAD * 48 / 10_000)  # bps


def validate_policy(policy, policy_deployer):
    runtime = policy.bytecode
    if policy.data_section_size:
        runtime = runtime[: -policy.data_section_size]
    if runtime != policy_deployer.compiler_data.bytecode_runtime:
        raise ValueError("Onchain runtime bytecode does not match the policy source")

    if policy.POOL().lower() != POOL.lower():
        raise ValueError("Onchain POOL does not match the deployment header")

    actual = (
        policy.FAST_HALF_LIFE(),
        policy.SLOW_HALF_LIFE(),
        policy.KAPPA(),
        policy.DEADBAND(),
        policy.MIN_CAP(),
        policy.MAX_CAP(),
    )
    expected = (
        FAST_HALF_LIFE,
        SLOW_HALF_LIFE,
        KAPPA,
        DEADBAND,
        MIN_CAP,
        MAX_CAP,
    )
    if actual != expected:
        raise ValueError(f"Onchain policy parameters do not match: {actual}")


def main():
    if POOL == "0x0000000000000000000000000000000000000000":
        raise ValueError("Set POOL before deploying")
    if not DRPC_API_KEY:
        raise ValueError("DRPC_API_KEY not found in environment")
    if not ETHERSCAN_API_KEY:
        raise ValueError("ETHERSCAN_API_KEY not found in environment")

    boa.set_network_env(RPC_URL)
    chain_id = boa.env.evm.patch.chain_id
    if chain_id != EXPECTED_CHAIN_ID:
        raise ValueError(f"Expected chain {EXPECTED_CHAIN_ID}, connected to {chain_id}")

    print(f"Chain: {chain_id}")
    print(f"Pool: {POOL}")

    constructor_args = (
        POOL,
        FAST_HALF_LIFE,
        SLOW_HALF_LIFE,
        KAPPA,
        DEADBAND,
        MIN_CAP,
        MAX_CAP,
    )
    policy_deployer = boa.load_partial("contracts/main/YBTwocryptoPolicy.vy")

    if POLICY_ADDRESS:
        # Boa requires a sender even for eth_call; no key or signer is loaded.
        boa.env.eoa = POLICY_ADDRESS
        policy = policy_deployer.at(POLICY_ADDRESS)
        policy.ctor_calldata = policy._ctor.prepare_calldata(*constructor_args)
        print(f"Verifying existing YBTwocryptoPolicy: {policy.address}")
    else:
        encrypted_pk = os.environ.get("ENCRYPTED_PK")
        if not encrypted_pk:
            raise ValueError("ENCRYPTED_PK not found in environment")

        private_key = decrypt_private_key(encrypted_pk, getpass())
        deployer = Account.from_key(private_key)
        boa.env.add_account(deployer)
        boa.env.eoa = deployer.address
        print(f"Deployer: {deployer.address}")

        policy = policy_deployer.deploy(*constructor_args)
        print(f"YBTwocryptoPolicy: {policy.address}")

    validate_policy(policy, policy_deployer)
    print("Runtime bytecode and immutable parameters match")

    etherscan_url = "https://api.etherscan.io/v2/api"
    boa.set_etherscan(etherscan_url, ETHERSCAN_API_KEY, chain_id=chain_id)
    verifier = Etherscan(etherscan_url, ETHERSCAN_API_KEY, chain_id=chain_id)
    try:
        boa.verify(policy, verifier=verifier, wait=True)
    except ValueError as exc:
        if "already verified" not in str(exc).lower():
            raise
        print("Contract already verified on Etherscan")


if __name__ == "__main__":
    main()
