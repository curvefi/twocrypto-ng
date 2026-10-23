"""Deploy YBOraclizedPolicy for the YieldBasis crvUSD/WETH pool and hand it to the DAO.

Run from the repository root: `uv run python scripts/deploy_yb_oraclized_policy.py`.
The signer deploys the policy, every parameter is read back, ownership moves to
the YieldBasis DAO, and the source is verified on Etherscan. Set CONFIG.policy to
an address an interrupted run printed to resume without redeploying.

Attaching the policy (pool.set_policy_contract) is a pool admin action, taken
separately by the factory admin.

Operating the attached policy (the contract source stays as deployed and verified):
- LT deposits must pass the debt that keeps the LevAMM book's ratio, solved from
  debt == pool.calc_token_amount([debt, assets], True) * amm.get_debt() // amm.collateral_amount()
  (proportional_debt in the policy tests). In 15 daily samples over the two weeks
  before deployment, a debt from a price, assets * price_oracle, sat 29 bp below
  to 85 bp above it, outside the 1 bp band every time. LT.preview_deposit does not run
  the check: verify the inequality and simulate the whole route.
- An A ramp: the owner sets base_fee to fallback_fee before the ramp. Once a swap
  past the ramp's end has checkpointed the final A (pool.last_timestamp() >=
  pool.future_A_gamma_time()), anyone calls sync() and the owner restores base_fee.
  The driver and the LT check keep running; killing the policy would turn the LT
  check off.
- The pool's admin fee must stay 0 for the LT check to measure deposited debt.
- The pool's get_dx can under-quote an input whose swap crosses the report and
  pays fallback_fee; confirm with get_dy.
- The keeper must deliver a report more often than report_lifetime (90 minutes).
  Past it, the averages and the target follow the pool's spot after the previous
  touch, as the pool's own EMA does.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import boa

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


if __name__ == "__main__":
    main()
