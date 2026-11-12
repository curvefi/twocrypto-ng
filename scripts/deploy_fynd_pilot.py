"""Deploy the Fynd pilot: a USDC/WETH pool from the Curve factory with FyndPolicy attached.

Run from the repository root:
    uv run python scripts/deploy_fynd_pilot.py --dry-run SIGNER
    uv run python scripts/deploy_fynd_pilot.py

Every run first replays the whole deployment on a fork of the latest block, then
sends it (unless --dry-run). Steps:
  1. factory.deploy_pool. Gamma is fx50's magic value: it lets the deployer call
     initialize, and no one can deposit before that (StableswapMath ignores gamma).
     The pool's code, and the math and view contracts it embeds, must match this
     repository's sources.
  2. FyndPolicy for this pool, owned by the signer.
  3. pool.initialize: reserved profit fraction 25%, admin fee 50%, the policy, and
     the market price (Uniswap's USDC/WETH spot, checked against Chainlink).
Then the policy is verified on Etherscan; the pool is a factory clone.
Liquidity is added separately. Until the first deposit, anyone may make it, at
any ratio: deposit soon after, at the pool's price_scale.

Resume after an interruption: set CONFIG.pool (and CONFIG.policy if the pool has
none yet) to the printed addresses and rerun.
"""

import argparse
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import boa
from eth_utils import keccak, to_checksum_address

USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
ZERO = "0x0000000000000000000000000000000000000000"

CONFIG = SimpleNamespace(
    rpc_url=os.environ.get("ETH_RPC_URL"),
    chain_id=1,
    factory="0x98EE851a00abeE0d95D08cF4CA2BdCE32aeaAF7F",
    implementation_id=int(keccak(text="fx50").hex(), 16),
    coin0=USDC,
    coin1=WETH,
    name="fynd-pilot wethusdc",
    symbol="fynd-wethusdc",
    # FyndPolicy. The owner (the signer) can change controller and router later.
    controller=None,  # Fynd's signing key: from Fynd
    router=None,  # Fynd's router contract: from Fynd
    emergency_admin="0x467947EE34aF926cF1DCac093870f613C96B1E0c",  # Curve emergency DAO
    default_fee=100_000_000,  # 1%: every operation without a Fynd grant
    min_fee=10**5,  # 0.1 bp, the pool's lowest fee: the lowest fee Fynd can sign
    # Resume: addresses an interrupted run printed. None deploys fresh.
    pool=None,
    policy=None,
)

POOL_PARAMS = {
    "A": 50_000,  # A = 5
    "gamma": 11_111_111_111,  # fx50 initialization magic
    "mid_fee": 100_000_000,  # 1%: the pool's own fee, used only without a policy
    "out_fee": 100_000_000,
    "fee_gamma": 10**16,  # no effect while mid_fee == out_fee
    "adjustment_step_min": 0,
    "adjustment_step_max": 5_000_000_000_000_000,  # 50 bp
    "ma_exp_time": 865,  # price oracle: 600 s half-life
}
RPF = 2_500_000_000  # reserved profit fraction 25%
ADMIN_FEE = 5_000_000_000  # 50% of the reserved profit

UNISWAP_USDC_WETH = "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640"  # Uniswap v3, 0.05%
CHAINLINK_ETH_USD = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"
# Chainlink ETH/USD updates on a 0.5% move or hourly, so allow a wider gap.
MAX_PRICE_GAP_BPS = 100
MAX_CHAINLINK_AGE = 3_600
# The pool's constructor logs Transfer(0, itself, 0): the mined receipt names the pool.
TRANSFER_TOPIC = "0x" + keccak(text="Transfer(address,address,uint256)").hex()
PRICE_ABI = """[
{"type":"function","name":"slot0","stateMutability":"view","inputs":[],"outputs":[{"name":"sqrtPriceX96","type":"uint160"},{"name":"tick","type":"int24"},{"name":"a","type":"uint16"},{"name":"b","type":"uint16"},{"name":"c","type":"uint16"},{"name":"d","type":"uint8"},{"name":"e","type":"bool"}]},
{"type":"function","name":"latestRoundData","stateMutability":"view","inputs":[],"outputs":[{"name":"roundId","type":"uint80"},{"name":"answer","type":"int256"},{"name":"startedAt","type":"uint256"},{"name":"updatedAt","type":"uint256"},{"name":"answeredInRound","type":"uint80"}]}
]"""


def chain_time():
    """The latest block's timestamp: the node's on mainnet, the fork's otherwise."""
    if isinstance(boa.env, boa.NetworkEnv):
        return int(boa.env._rpc.fetch("eth_getBlockByNumber", ["latest", False])["timestamp"], 16)
    return boa.env.evm.patch.timestamp


def market_price():
    """USDC per WETH, 1e18: Uniswap's spot, checked against Chainlink's ETH/USD."""
    oracle = boa.loads_abi(PRICE_ABI, name="PriceSource")
    sqrt_price = oracle.at(UNISWAP_USDC_WETH).slot0()[0]
    uniswap = 10**30 * 2**192 // sqrt_price**2  # USDC per WETH, 1e18
    _, answer, _, updated_at, _ = oracle.at(CHAINLINK_ETH_USD).latestRoundData()
    age = chain_time() - updated_at
    if answer <= 0 or not 0 <= age <= MAX_CHAINLINK_AGE:
        raise RuntimeError(f"Chainlink ETH/USD is {answer}, {age} s old")
    chainlink = answer * 10**10
    gap_bps = abs(uniswap - chainlink) * 10_000 / chainlink
    print(
        f"WETH: Uniswap {uniswap / 1e18:,.2f} USDC, Chainlink {chainlink / 1e18:,.2f} USD "
        f"({gap_bps:.1f} bp apart)"
    )
    if gap_bps > MAX_PRICE_GAP_BPS:
        raise RuntimeError(f"Uniswap and Chainlink differ by more than {MAX_PRICE_GAP_BPS} bp")
    return uniswap


LAST_RECEIPT = {}


def record_receipts():
    """
    Keep each mined receipt. On mainnet without tracing, boa returns a call's
    simulated result, and a pool another deployer creates first in the same block
    would move ours to a different address than the simulation's.
    """
    send = boa.env._send_txn

    def recording(*args, **kwargs):
        txdata, receipt, trace = send(*args, **kwargs)
        LAST_RECEIPT["receipt"] = receipt
        return txdata, receipt, trace

    boa.env._send_txn = recording


def created_pool(simulated):
    """The pool deploy_pool created: the mined receipt's, or on a fork the simulated one."""
    receipt = LAST_RECEIPT.pop("receipt", None)
    if receipt is None:
        return simulated
    zero = "0x" + "00" * 32
    for log in receipt["logs"]:
        topics = log["topics"]
        if (
            len(topics) == 3
            and topics[0] == TRANSFER_TOPIC
            and topics[1] == zero
            and int(topics[2], 16) == int(log["address"], 16)
        ):
            return to_checksum_address(log["address"])
    raise RuntimeError("The deploy_pool receipt has no pool creation log")


def runtime(contract):
    """Deployed code without its immutables."""
    code = contract.bytecode
    return code[: -contract.data_section_size] if contract.data_section_size else code


def check_code(pool):
    """Raise unless the pool and the math and view contracts it embeds run our sources."""
    for path, address in (
        ("contracts/main/Twocrypto.vy", pool.address),
        ("contracts/main/StableswapMath.vy", pool.MATH()),
        ("contracts/main/TwocryptoView.vy", pool.VIEW()),
    ):
        source = boa.load_partial(path)
        if runtime(source.at(address)) != source.compiler_data.bytecode_runtime:
            raise RuntimeError(f"Code at {address} does not match {path}")


def unpack_3(packed):
    mask = 2**64 - 1
    return [packed >> 128 & mask, packed >> 64 & mask, packed & mask]


def policy_args(cfg, pool):
    return (
        pool,
        cfg.controller,
        cfg.router,
        cfg.emergency_admin,
        cfg.default_fee,
        cfg.min_fee,
    )


def deploy(signer, cfg=CONFIG):
    """Run or resume the steps; return (pool, policy)."""
    factory = boa.load_partial("contracts/main/TwocryptoFactory.vy").at(cfg.factory)
    pool_source = boa.load_partial("contracts/main/Twocrypto.vy")
    policy_source = boa.load_partial("contracts/main/FyndPolicy.vy")

    # 1. Pool
    if cfg.pool:
        pool = pool_source.at(cfg.pool)
        print(f"Reusing pool: {pool.address}")
    else:
        if str(factory.pool_implementations(cfg.implementation_id)) == ZERO:
            raise RuntimeError("Factory has no fx50 pool implementation")
        LAST_RECEIPT.clear()
        simulated = factory.deploy_pool(
            cfg.name,
            cfg.symbol,
            [cfg.coin0, cfg.coin1],
            cfg.implementation_id,
            *POOL_PARAMS.values(),
            market_price(),
        )
        pool = pool_source.at(created_pool(simulated))
        print(f"Pool deployed: {pool.address} (CONFIG.pool to resume)")
    check_code(pool)

    # 2. Policy
    args = policy_args(cfg, pool.address)
    attached = str(pool.POLICY())
    if cfg.policy or attached != ZERO:
        policy = policy_source.at(cfg.policy or attached)
        # Etherscan verification needs the deployment's constructor arguments.
        policy.ctor_calldata = policy._ctor.prepare_calldata(*args)
        print(f"Reusing policy: {policy.address}")
    else:
        policy = policy_source.deploy(*args)
        print(f"Policy deployed: {policy.address} (CONFIG.policy to resume)")

    # 3. Initialize, with a fresh price: it cannot be repeated.
    if str(pool.POLICY()) == ZERO:
        if pool.D() != 0:
            raise RuntimeError("Pool has liquidity but no policy")
        initial_price = market_price()
        pool.initialize(RPF, ADMIN_FEE, policy.address, initial_price, [])
        print(f"Pool initialized at {initial_price / 1e18:,.2f}")

    check(pool, policy, policy_source, signer, cfg)
    return pool, policy


def check(pool, policy, policy_source, signer, cfg):
    """Raise unless the pool and the policy match CONFIG."""
    actual = {
        "A": pool.A(),
        "gamma": pool.gamma(),
        "mid_fee": pool.mid_fee(),
        "out_fee": pool.out_fee(),
        "fee_gamma": pool.fee_gamma(),
        **dict(
            zip(
                ("adjustment_step_min", "adjustment_step_max", "ma_exp_time"),
                unpack_3(pool.packed_rebalancing_params()),
            )
        ),
    }
    for name, value in POOL_PARAMS.items():
        if actual[name] != value:
            raise RuntimeError(f"Pool {name} is {actual[name]}, expected {value}")
    coins = [str(pool.coins(0)).lower(), str(pool.coins(1)).lower()]
    if coins != [cfg.coin0.lower(), cfg.coin1.lower()] or pool.name() != cfg.name:
        raise RuntimeError(f"Pool is {pool.name()} with coins {coins}")
    if (pool.reserved_profit_fraction(), pool.admin_fee()) != (RPF, ADMIN_FEE):
        raise RuntimeError("Pool reserved profit fraction or admin fee differ")
    if str(pool.POLICY()).lower() != policy.address.lower():
        raise RuntimeError("Pool is not attached to the policy")
    if pool.lp_allowlist(ZERO) or pool.donation_shares() != 0:
        raise RuntimeError("Pool has an LP allowlist or donation shares")

    if runtime(policy) != policy_source.compiler_data.bytecode_runtime:
        raise RuntimeError("Onchain runtime bytecode does not match the policy source")
    expected = {
        "POOL": pool.address,
        "controller": cfg.controller,
        "router": cfg.router,
        "EMERGENCY_ADMIN": cfg.emergency_admin,
        "default_fee": cfg.default_fee,
        "min_fee": cfg.min_fee,
        "owner": signer,
    }
    for name, value in expected.items():
        actual_value = getattr(policy, name)()
        if str(actual_value).lower() != str(value).lower():
            raise RuntimeError(f"Policy {name} is {actual_value}, expected {value}")
    if policy.is_killed():
        raise RuntimeError("Policy is killed")
    print("Checked: pool settings, reserved profit 25%, admin fee 50%, policy code and settings")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", metavar="SIGNER", help="fork rehearsal only, as SIGNER")
    dry_run = parser.parse_args().dry_run

    cfg = CONFIG
    if not cfg.rpc_url:
        raise ValueError("ETH_RPC_URL is required")
    missing = [n for n in ("name", "symbol", "controller", "router") if not getattr(cfg, n)]
    if missing:
        raise ValueError(f"Set CONFIG.{', CONFIG.'.join(missing)}")

    signer = None
    if not dry_run:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from eth_account import Account
        from secure_key_utils import decrypt_private_key, getpass

        encrypted_key = os.environ.get("ENCRYPTED_PK")
        if not encrypted_key:
            raise ValueError("ENCRYPTED_PK is required")
        etherscan_api_key = os.environ.get("ETHERSCAN_API_KEY")
        if not etherscan_api_key:
            raise ValueError("ETHERSCAN_API_KEY is required to verify the policy")
        signer = Account.from_key(decrypt_private_key(encrypted_key, getpass()))
    sender = to_checksum_address(dry_run) if dry_run else signer.address
    print(f"Signer: {sender}")

    # Rehearsal on a fork of the latest block, sending as the signer without signing.
    with boa.fork(cfg.rpc_url, block_identifier="latest", allow_dirty=True):
        if boa.env.evm.patch.chain_id != cfg.chain_id:
            raise ValueError(f"Expected chain {cfg.chain_id}")
        boa.env.eoa = sender
        deploy(sender)
    print("Fork rehearsal passed")
    if dry_run:
        return

    boa.set_network_env(cfg.rpc_url)
    # Traces are diagnostics only; a lagging RPC node must not abort after a mined tx.
    boa.env.suppress_debug_tt()
    if boa.env.evm.patch.chain_id != cfg.chain_id:
        raise ValueError(f"Expected chain {cfg.chain_id}")
    boa.env.add_account(signer)
    boa.env.eoa = signer.address
    record_receipts()
    pool, policy = deploy(signer.address)

    from boa.explorer import Etherscan

    try:
        verifier = Etherscan(api_key=etherscan_api_key, chain_id=cfg.chain_id)
        boa.verify(policy, verifier=verifier, wait=True)
        print(f"Verified: https://etherscan.io/address/{policy.address}#code")
    except Exception as exc:  # The onchain steps are done; only verification needs a retry.
        print(f"Verification failed: {exc}. Rerun with CONFIG.pool and CONFIG.policy set.")
    print(f"Pool {pool.address}, policy {policy.address}")


if __name__ == "__main__":
    main()
