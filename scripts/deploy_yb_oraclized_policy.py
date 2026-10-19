"""Deploy YBOraclizedPolicy for the YieldBasis crvUSD/WETH pool and hand it to the DAO.

Run from the repository root: `uv run python scripts/deploy_yb_oraclized_policy.py`.
The signer deploys the policy, every parameter is read back, ownership moves to
the YieldBasis DAO, and the source is verified on Etherscan. Set CONFIG.policy to
an address an interrupted run printed to resume without redeploying.

Attaching the policy (pool.set_policy_contract) is a pool admin action: a Curve
DAO vote through the factory admin. It is not taken here; the script prints the
calldata, together with the backtest's companion pool and LevAMM settings.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import boa
from eth_abi import encode
from eth_utils import keccak

WAD = 10**18

CONFIG = SimpleNamespace(
    rpc_url=os.environ.get("ETH_RPC_URL"),
    chain_id=1,
    pool="0x656341Ef90b622c6634e0573772FfB7f3669b9f3",  # YieldBasis crvUSD/WETH
    amm="0x5f8D24F33Cc5a1D5D1bf012261E6A2214C92233c",  # LevAMM of YieldBasis market 10
    feed_id=2,  # Pyth Pro Crypto.ETH/USD (immutable)
    # OracleConfig: report admission, owner-settable after deployment.
    oracle=(
        "0xACeA761c27A909d4D3895128EBe6370FDE2dF481",  # Pyth Lazer verifier (UUPS proxy)
        4,  # channel: fixed_rate@1000ms, the whole-second reports the backtest replays
        12_000_000,  # past_window_us: observation up to 12 s before the block
        6_000_000,  # future_window_us: message up to 6 s after the block
        100 * WAD,  # min_price: $100 per ETH
        100_000 * WAD,  # max_price: $100,000 per ETH
    ),
    emergency_admin="0x467947EE34aF926cF1DCac093870f613C96B1E0c",  # Curve emergency DAO
    owner="0x42F2A41A0D0e65A440813190880c8a65124895Fa",  # YieldBasis DAO
    # PolicyConfig(fee, driver, ratio_tolerance), owner-settable after deployment.
    # top100-128x128-don01to35-rpf20to50-1638400-20261019 (report_lean with
    # report_lifetime_s, live pool settings, hourly or fallback-fee report keeper),
    # replay ordinal 521415. Fees in 1e10, capture and relative values in WAD.
    config=(
        (
            50_000_000,  # base_fee: 50 bp
            675 * WAD // 1_000,  # capture: 0.675
            175_000_000,  # fallback_fee: 175 bp
            300,  # relax_time: seconds
        ),
        (
            4_800,  # fast_half_life: seconds (80 min)
            9_600,  # slow_half_life: seconds (160 min)
            7 * WAD // 1_000,  # trend_gate: 70 bp
            5 * WAD // 1_000,  # step_cap: 50 bp per touch
            5_400,  # report_lifetime: seconds (90 min)
        ),
        WAD // 10_000,  # ratio_tolerance: LT deposit band, 1 bp
    ),
    # The replay's market settings outside the policy, printed as calldata. It assumes
    # YieldBasis donations of 1.17% a year (pool.donation_apy, a backtest assumption, not
    # a setting) and a keeper that delivers a report with a dust swap once the stored
    # report or the last pool touch is an hour old, or Pyth has moved the fallback fee
    # from the stored report.
    reserved_profit_fraction=4_220_472_400,  # pool, 1e10: 42.204724%, the replay's. Curve DAO.
    amm_fee=15 * 10**15,  # LevAMM fee via LT.set_amm_fee, 1e18: 1.5%. LT admin.
    lt="0x2B9c9f3BdcEb5d8E36a4704f08a78Fca53343cEa",  # LT of YieldBasis market 10
    policy=None,  # Resume: the address of an earlier deployment.
)


def constructor_args(cfg):
    return (cfg.pool, cfg.amm, cfg.feed_id, cfg.emergency_admin, cfg.oracle, cfg.config)


def check(policy, policy_source, cfg):
    """Raise unless the deployed code and every parameter match CONFIG."""
    runtime = policy.bytecode
    if policy.data_section_size:
        runtime = runtime[: -policy.data_section_size]
    if runtime != policy_source.compiler_data.bytecode_runtime:
        raise RuntimeError("Onchain runtime bytecode does not match the policy source")

    expected = {
        "POOL": cfg.pool,
        "AMM": cfg.amm,
        "FEED_ID": cfg.feed_id,
        "EMERGENCY_ADMIN": cfg.emergency_admin,
    }
    for name, value in expected.items():
        actual = getattr(policy, name)()
        if str(actual).lower() != str(value).lower():
            raise RuntimeError(f"{name} is {actual}, expected {value}")
    oracle = tuple(policy.oracle())
    if (str(oracle[0]).lower(), *oracle[1:]) != (cfg.oracle[0].lower(), *cfg.oracle[1:]):
        raise RuntimeError(f"oracle is {policy.oracle()}, expected {cfg.oracle}")
    if policy.config() != cfg.config:
        raise RuntimeError(f"config is {policy.config()}, expected {cfg.config}")
    if policy.is_killed():
        raise RuntimeError("Policy is killed")


def deploy(policy_source, cfg):
    """Deploy or resume, check every parameter, and transfer ownership to cfg.owner."""
    args = constructor_args(cfg)
    if cfg.policy:
        policy = policy_source.at(cfg.policy)
        # Etherscan verification needs the constructor arguments of the deployment.
        policy.ctor_calldata = policy._ctor.prepare_calldata(*args)
        print(f"Reusing policy: {policy.address}")
    else:
        policy = policy_source.deploy(*args)
        print(f"Policy deployed: {policy.address} (CONFIG.policy to resume)")
    check(policy, policy_source, cfg)

    owner = str(policy.owner()).lower()
    if owner != cfg.owner.lower():
        if owner != str(boa.env.eoa).lower():
            raise RuntimeError(f"Policy is owned by {policy.owner()}, not the signer or the DAO")
        policy.transfer_ownership(cfg.owner)
    if str(policy.owner()).lower() != cfg.owner.lower():
        raise RuntimeError("Ownership transfer to the DAO did not land")
    print(f"Owner: {policy.owner()}")
    return policy


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from boa.explorer import Etherscan
    from eth_account import Account
    from secure_key_utils import decrypt_private_key, getpass

    cfg = CONFIG
    if not cfg.rpc_url:
        raise ValueError("ETH_RPC_URL is required")
    if not cfg.amm:
        raise ValueError("Set CONFIG.amm to the market's LevAMM")
    etherscan_api_key = os.environ.get("ETHERSCAN_API_KEY")
    if not etherscan_api_key:
        raise ValueError("ETHERSCAN_API_KEY is required to verify the policy")

    boa.set_network_env(cfg.rpc_url)
    # Traces are diagnostics only; a lagging RPC node must not abort after a mined tx.
    boa.env.suppress_debug_tt()
    if boa.env.evm.patch.chain_id != cfg.chain_id:
        raise ValueError(f"Expected chain {cfg.chain_id}, got {boa.env.evm.patch.chain_id}")
    if not boa.env.get_code(cfg.oracle[0]):
        raise ValueError("Pyth verifier has no code on this chain")

    policy_source = boa.load_partial("contracts/main/YBOraclizedPolicy.vy")
    needs_signer = True
    if cfg.policy:
        # Boa needs a sender even for eth_call. A policy the DAO already owns only
        # needs checking; one still owned by the signer needs its transfer.
        boa.env.eoa = cfg.policy
        needs_signer = str(policy_source.at(cfg.policy).owner()).lower() != cfg.owner.lower()
    if needs_signer:
        encrypted_key = os.environ.get("ENCRYPTED_PK")
        if not encrypted_key:
            raise ValueError("ENCRYPTED_PK is required")
        signer = Account.from_key(decrypt_private_key(encrypted_key, getpass()))
        boa.env.add_account(signer)
        boa.env.eoa = signer.address
        print(f"Signer: {signer.address}")
    policy = deploy(policy_source, cfg)

    verifier = Etherscan(api_key=etherscan_api_key, chain_id=cfg.chain_id)
    try:
        boa.verify(policy, verifier=verifier, wait=True)
        print(f"Policy verified: https://etherscan.io/address/{policy.address}#code")
    except Exception as exc:  # The onchain steps are done; only verification needs a retry.
        print(f"Verification failed: {exc}. Rerun with CONFIG.policy set.")

    for target, call, caller in companion_calls(policy.address, cfg, pool_admin_fee(cfg)):
        print(f"{caller}: call {target} with 0x{call.hex()}")


ADMIN_FEE_ABI = '[{"type":"function","name":"admin_fee","stateMutability":"view","inputs":[],"outputs":[{"name":"","type":"uint256"}]}]'


def pool_admin_fee(cfg):
    """The pool's live admin_fee: set_fee_parameters sets it together with the RPF."""
    return boa.loads_abi(ADMIN_FEE_ABI, name="Pool").at(cfg.pool).admin_fee()


def companion_calls(policy, cfg, admin_fee):
    """(target, calldata, who calls it): attach the policy plus the backtest's market settings."""

    def calldata(signature, types, args):
        return keccak(text=signature)[:4] + encode(types, args)

    return [
        (
            cfg.pool,
            calldata("set_policy_contract(address)", ["address"], [policy]),
            "Curve DAO (pool admin): set_policy_contract",
        ),
        (
            cfg.pool,
            calldata(
                "set_fee_parameters(uint256,uint256)",
                ["uint256", "uint256"],
                [cfg.reserved_profit_fraction, admin_fee],
            ),
            f"Curve DAO (pool admin): set_fee_parameters, admin_fee kept at {admin_fee}",
        ),
        (
            cfg.lt,
            calldata("set_amm_fee(uint256)", ["uint256"], [cfg.amm_fee]),
            "YieldBasis (LT admin): set_amm_fee",
        ),
    ]


if __name__ == "__main__":
    main()
