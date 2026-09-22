"""Deploy a factory Twocrypto pool, its oracle policy, then initialize the pool.

Edit CONFIG below, then run this file from the repository root. The fx50 pool's
special gamma lets the deployer initialize it without being the factory admin.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import boa
from boa.explorer import Etherscan
from dotenv import load_dotenv
from eth_account import Account
from eth_utils import keccak

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from secure_key_utils import decrypt_private_key, getpass  # noqa: E402

load_dotenv(Path(__file__).with_name(".env"))

# Fill these chain-specific values before running. Keys stay in ENCRYPTED_PK.
CONFIG = SimpleNamespace(
    rpc_url=os.environ.get("ETH_RPC_URL"),
    chain_id=1,
    factory="0x98EE851a00abeE0d95D08cF4CA2BdCE32aeaAF7F",
    # The reference crvUSD/WETH pool was deployed with the fx50 implementation.
    implementation_id=int(keccak(text="fx50").hex(), 16),
    coin0="0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E",  # crvUSD
    coin1="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
    initial_price=2_750 * 10**18,  # crvUSD per WETH; check before deployment.
    pyth_verifier="0xACeA761c27A909d4D3895128EBe6370FDE2dF481",
    feed_id=2,  # Pyth Pro Crypto.ETH/USD
    channel=3,  # fixed_rate@200ms
    name="Curve.fi crvUSD/WETH Oracle Test",
    symbol="crvUSD/WETH-OT",
    rpf_bps=2_500,
    admin_fee_bps=0,
)

WAD = 10**18
FEE_PRECISION = 10**10
A_MULTIPLIER = 10_000
BOOTSTRAP_GAMMA = 11_111_111_111
PLANNED_DONATION_BPS = 150  # 1.5% offchain donation plan; no donation transaction here.

# Target: sqrt fixed-offset scan, ordinal 370864; RPF and donation are rounded.
# Bootstrap gamma differs from that scan's 100_000_000_000_000 gamma.
# Other pool settings come from the scan's native-fresh-10m template.
# The factory's last three arguments are min step, max step, and EMA exponent time.
POOL_PARAMS = {
    "A": 5 * A_MULTIPLIER,
    "mid_fee": 150_000_000,
    "out_fee": 150_000_000,
    "fee_gamma": 30_000_000_000_000_000,
    "allowed_extra_profit": 100_000_000,
    "adjustment_step": 30_000_000_000_000_000,
    "ma_exp_time": 600,
}
# Screenshot policy_params.4..9: 1500 / 50400 / 1.14 / 0.0015 / 0.001 / 0.005.
DRIVER_PARAMS = (
    1_500,
    50_400,
    114 * WAD // 100,
    15 * WAD // 10_000,
    10 * WAD // 10_000,
    50 * WAD // 10_000,
)
# Scan policy_params: base=30 bp, capture=82.5%, fallback=150 bp, expiry=300 s.
# The 12-second report admission window is specific to this onchain policy.
FEE_PARAMS = (150_000_000, 30_000_000, 825 * WAD // 1_000, 12_000, 300)


def deploy(factory, pool_source, policy_source, args):
    """Run the deployment after the signer and chain have been selected."""
    if int(factory.pool_implementations(args.implementation_id), 16) == 0:
        raise ValueError("Factory has no pool implementation at this ID")
    if not boa.env.get_code(args.pyth_verifier):
        raise ValueError("Pyth verifier has no code on this chain")
    if not 0 <= args.rpf_bps <= 10_000 or not 0 <= args.admin_fee_bps <= 9_000:
        raise ValueError("RPF must be 0..10000 bp and admin fee 0..9000 bp")

    rpf = args.rpf_bps * FEE_PRECISION // 10_000
    admin_fee = args.admin_fee_bps * FEE_PRECISION // 10_000
    print(f"Deploying with initialization gamma {BOOTSTRAP_GAMMA}")
    pool_address = factory.deploy_pool(
        args.name,
        args.symbol,
        [args.coin0, args.coin1],
        args.implementation_id,
        POOL_PARAMS["A"],
        BOOTSTRAP_GAMMA,
        POOL_PARAMS["mid_fee"],
        POOL_PARAMS["out_fee"],
        POOL_PARAMS["fee_gamma"],
        POOL_PARAMS["allowed_extra_profit"],
        POOL_PARAMS["adjustment_step"],
        POOL_PARAMS["ma_exp_time"],
        args.initial_price,
    )
    # Boa returns only after the pool deployment transaction is mined.
    print(f"Pool deployed: {pool_address}")
    pool = pool_source.at(pool_address)

    policy = policy_source.deploy(
        pool_address,
        *DRIVER_PARAMS,
        args.pyth_verifier,
        args.feed_id,
        args.channel,
        FEE_PARAMS,
    )
    # Likewise, the policy deployment must be mined before initialization.
    print(f"Policy deployed: {policy.address}")

    pool.initialize(rpf, admin_fee, policy.address, args.initial_price, [])

    if (
        pool.POLICY().lower() != policy.address.lower()
        or pool.reserved_profit_fraction() != rpf
        or pool.admin_fee() != admin_fee
        or pool.A() != POOL_PARAMS["A"]
        or pool.gamma() != BOOTSTRAP_GAMMA
        or pool.mid_fee() != POOL_PARAMS["mid_fee"]
        or pool.out_fee() != POOL_PARAMS["out_fee"]
        or pool.fee_gamma() != POOL_PARAMS["fee_gamma"]
        or policy.POOL().lower() != pool_address.lower()
        or policy.POOL_A() != POOL_PARAMS["A"]
    ):
        raise RuntimeError("Pool/policy readback did not match deployment settings")
    print(f"Pool configured: RPF={args.rpf_bps} bp, admin fee={args.admin_fee_bps} bp")
    print(f"Planned donation: {PLANNED_DONATION_BPS} bp (offchain; not submitted)")
    return pool_address, policy


def main():
    if not CONFIG.rpc_url or CONFIG.chain_id <= 0:
        raise ValueError("Set CONFIG.rpc_url and CONFIG.chain_id")
    if not all(
        (CONFIG.factory, CONFIG.coin0, CONFIG.coin1, CONFIG.initial_price, CONFIG.pyth_verifier)
    ):
        raise ValueError("Set the factory, coins, initial price, and Pyth verifier in CONFIG")
    encrypted_key = os.environ.get("ENCRYPTED_PK")
    if not encrypted_key:
        raise ValueError("ENCRYPTED_PK is required")
    etherscan_api_key = os.environ.get("ETHERSCAN_API_KEY")
    if not etherscan_api_key:
        raise ValueError("ETHERSCAN_API_KEY is required to verify the policy")

    boa.set_network_env(CONFIG.rpc_url)
    if boa.env.evm.patch.chain_id != CONFIG.chain_id:
        raise ValueError(f"Expected chain {CONFIG.chain_id}, got {boa.env.evm.patch.chain_id}")
    signer = Account.from_key(decrypt_private_key(encrypted_key, getpass()))
    boa.env.add_account(signer)
    boa.env.eoa = signer.address
    print(f"Chain: {CONFIG.chain_id}; signer: {signer.address}")

    factory = boa.load_partial("contracts/main/TwocryptoFactory.vy").at(CONFIG.factory)
    pool_source = boa.load_partial("contracts/main/Twocrypto.vy")
    policy_source = boa.load_partial("contracts/main/YBOraclizedPolicy.vy")
    _, policy = deploy(factory, pool_source, policy_source, CONFIG)

    verifier = Etherscan(api_key=etherscan_api_key, chain_id=CONFIG.chain_id)
    boa.verify(policy, verifier=verifier, wait=True)
    print(f"Policy verified: https://etherscan.io/address/{policy.address}#code")


if __name__ == "__main__":
    main()
