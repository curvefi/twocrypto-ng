"""Deploy YBOraclizedPolicy for a YieldBasis market and hand it to the DAO.

MARKET selects the market: weth (default), wbtc, cbbtc or tbtc. The policy reads
Pyth reports from the price-only PythReportBank (CONFIG.bank, from the
lib/pyth-report-bank submodule, curvefi/pyth-report-bank). WBTC and tBTC are
priced as BTC/USD times their Curve basis pool's price_oracle(0) against cbBTC,
tBTC's inverted; cbBTC counts as BTC.

Run from the repository root: `MARKET=wbtc uv run python scripts/deploy_yb_oraclized_policy.py`,
with ETH_RPC_URL and ETHERSCAN_API_KEY set. The deployer CONFIG.deployer signs: its
key opens only with a YubiKey touch and then the keystore password
(scripts/yubi_deployers.py, a verbatim copy from the yubi-deployers project; the
key file is ~/.config/eth/<deployer>.json.age, and `age` and `age-plugin-yubikey`
must be on PATH). The deployer deploys the policy, every parameter is read back,
ownership moves to the YieldBasis DAO, and the source is verified on Etherscan.
Set CONFIG.policy to an address an interrupted run printed to resume without
redeploying; a resumed policy the DAO already owns is checked and verified
without the key.

Attaching the policy (pool.set_policy_contract) is a pool admin action, taken
separately by the factory admin.

Operating the attached policy (the contract source stays as deployed and verified):
- LT deposits must pass the debt that keeps the LevAMM book's ratio, solved from
  debt == pool.calc_token_amount([debt, assets], True) * amm.get_debt() // amm.collateral_amount()
  (proportional_debt in the policy tests). On the WETH market, in 15 daily samples
  over the two weeks before its October 2026 deployment, a debt from a price,
  assets * price_oracle, sat 29 bp below to 85 bp above it, outside the 1 bp band
  every time; other markets were not sampled. LT.preview_deposit does not run
  the check: verify the inequality and simulate the whole route.
- An A ramp: the owner sets base_fee to fallback_fee before the ramp. Once a swap
  past the ramp's end has checkpointed the final A (pool.last_timestamp() >=
  pool.future_A_gamma_time()), anyone calls sync() and the owner restores base_fee.
  The driver and the LT check keep running; killing the policy would turn the LT
  check off.
- The pool's admin fee must stay 0 for the LT check to measure deposited debt.
- The pool's get_dx can under-quote an input whose swap crosses the report and
  pays fallback_fee; confirm with get_dy.
- The keeper must deliver a report to the bank (deliver_report, an update whose
  feeds carry price, exponent and feed update time) more often than
  report_lifetime (90 minutes). Past it, the averages and the target follow the
  pool's spot after the previous touch, as the pool's own EMA does. A delivery
  prices fees at once; the averages move on the pool's next operation.
- Whenever policy.cached_supply() differs from pool.user_supply() while the
  policy is live, a balanced removal's best-effort callback failed: call sync().
  Until then the LT check can miss one deposit.
- Fees read the crvUSD rate when they are priced: the aggregator's last_price()
  while at most 4 hours old, else its price() view, which costs every swap more
  until someone calls price_w() on the aggregator.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import boa

WAD = 10**18
ZERO = "0x0000000000000000000000000000000000000000"
WBTC = "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599"
CBBTC = "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf"
TBTC = "0x18084fbA666a33d37592fA2633fD49a74DD93a88"

# Every market: the same bank, DAO roles, math, crvUSD aggregator and parameters.
COMMON = dict(
    rpc_url=os.environ.get("ETH_RPC_URL"),
    chain_id=1,
    # StableswapMath of every pool below; the policy copies its get_p (checked on the pool)
    math="0xBfDdF58Cb6ef84e115fF47c10e49A80B2653EA13",
    # crvUSD PriceAggregator, which the policy reads through the LevAMM's price oracle (checked).
    aggregator="0x18672b1b0c623a30089A280Ed9256379fb0E4E62",
    bank="0x8a0f866de34631311b7745C5f4eec7Bf1F6849dB",  # PythReportBank, 60 s delivery window (immutable)
    channel=4,  # fixed_rate@1000ms, the whole-second reports the backtest replays (immutable)
    emergency_admin="0x467947EE34aF926cF1DCac093870f613C96B1E0c",  # Curve emergency DAO
    owner="0x42F2A41A0D0e65A440813190880c8a65124895Fa",  # YieldBasis DAO
    # The YubiKey-held key ~/.config/eth/<deployer>.json.age signs the deployment.
    deployer="0xb101b2b0aa02b7167D238B98dc1B0b0404a760E8",
    ratio_tolerance=WAD // 10_000,  # LT deposit band, 1 bp; owner-settable
    policy=None,  # Resume: the address of an earlier deployment.
)


def policy_config(base_fee, capture, fast_half_life, slow_half_life, trend_gate, step_cap):
    """
    PolicyConfig(fee, driver) of a curve-fx-sim finalist (finalists/README.md,
    2026-11-13). Every market: fallback_fee 200 bp, relax_time 90 s, report_lifetime
    5,400 s. Fees in 1e10, capture and relative values in WAD, times in seconds.
    """
    return (
        (base_fee, capture, 200_000_000, 90),
        (fast_half_life, slow_half_life, trend_gate, step_cap, 5_400),
    )


# Per market: pool, LevAMM, Pyth feed (immutable), basis pool and its expected
# (coin0, coin1) (immutable), PriceBounds on coin1 in USD and PolicyConfig
# (owner-settable).
MARKETS = dict(
    weth=dict(  # YieldBasis market 10
        pool="0x656341Ef90b622c6634e0573772FfB7f3669b9f3",
        amm="0x5f8D24F33Cc5a1D5D1bf012261E6A2214C92233c",
        feed_id=2,  # Pyth Pro Crypto.ETH/USD
        basis_pool=ZERO,  # none: WETH is priced as ETH
        invert_basis=False,
        basis_coins=None,
        bounds=(100 * WAD, 100_000 * WAD),
        # base 60 bp, capture 0.80, half-lives 90/180 min, gate 75 bp, step 50 bp
        config=policy_config(
            60_000_000, 800 * WAD // 1_000, 5_400, 10_800, 75 * WAD // 10_000, 50 * WAD // 10_000
        ),
    ),
    wbtc=dict(  # YieldBasis market 7
        pool="0x313698667d7FDD6789a9BC70821309ff891E729A",
        amm="0x7b9817eb5C49A99875138A5d52bF64a8B2cFFFFE",
        feed_id=1,  # Pyth Pro Crypto.BTC/USD
        basis_pool="0x839d6bDeDFF886404A6d7a788ef241e4e28F4802",  # price_oracle(0): WBTC in cbBTC
        invert_basis=False,
        basis_coins=(CBBTC, WBTC),
        bounds=(1_000 * WAD, 5_000_000 * WAD),
        # as cbBTC, gate 28 bp
        config=policy_config(
            30_000_000, 875 * WAD // 1_000, 7_200, 18_000, 28 * WAD // 10_000, 30 * WAD // 10_000
        ),
    ),
    cbbtc=dict(  # YieldBasis market 8
        pool="0x862CB4E988FB66E72f128d1183829f8c05B6c6A0",
        amm="0x49F51d7e279252F3C9a09678fdC65B4dBd5CB196",
        feed_id=1,
        basis_pool=ZERO,  # none: cbBTC is priced as BTC
        invert_basis=False,
        basis_coins=None,
        bounds=(1_000 * WAD, 5_000_000 * WAD),
        # base 30 bp, capture 0.875, half-lives 120/300 min, gate 42 bp, step 30 bp
        config=policy_config(
            30_000_000, 875 * WAD // 1_000, 7_200, 18_000, 42 * WAD // 10_000, 30 * WAD // 10_000
        ),
    ),
    tbtc=dict(  # YieldBasis market 9
        pool="0x4F52C3a81E33521e5a9A47FD9D3BE475D2279c2e",
        amm="0x0e357Af536592F275C6Aa07b8AC2CA6EB3d0cF5a",
        feed_id=1,
        basis_pool="0xAE6Ee608b297305AbF3EB609B81FEBbb8F6A0bb3",  # price_oracle(0): cbBTC in tBTC
        invert_basis=True,
        basis_coins=(TBTC, CBBTC),
        bounds=(1_000 * WAD, 5_000_000 * WAD),
        # as WBTC: same policy and point (tBTC itself was not simulated)
        config=policy_config(
            30_000_000, 875 * WAD // 1_000, 7_200, 18_000, 28 * WAD // 10_000, 30 * WAD // 10_000
        ),
    ),
)

CONFIG = SimpleNamespace(**COMMON, **MARKETS[os.environ.get("MARKET", "weth")])

# ABI stubs for check(): the policy pool's math and the basis pool's coins.
POOL_STUB = """
@external
@view
def MATH() -> address:
    return empty(address)
"""
BASIS_POOL_STUB = """
@external
@view
def coins(i: uint256) -> address:
    return empty(address)
"""


def constructor_args(cfg):
    return (
        cfg.pool,
        cfg.amm,
        cfg.bank,
        cfg.feed_id,
        cfg.channel,
        cfg.basis_pool,
        cfg.invert_basis,
        cfg.emergency_admin,
        cfg.bounds,
        cfg.config,
        cfg.ratio_tolerance,
    )


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
        "BANK": cfg.bank,
        "AGGREGATOR": cfg.aggregator,
        "FEED_ID": cfg.feed_id,
        "CHANNEL": cfg.channel,
        "BASIS_POOL": cfg.basis_pool,
        "INVERT_BASIS": cfg.invert_basis,
        "EMERGENCY_ADMIN": cfg.emergency_admin,
    }
    for name, value in expected.items():
        actual = getattr(policy, name)()
        if str(actual).lower() != str(value).lower():
            raise RuntimeError(f"{name} is {actual}, expected {value}")
    pool_math = boa.loads_partial(POOL_STUB).at(cfg.pool).MATH()
    if str(pool_math).lower() != cfg.math.lower():
        raise RuntimeError(f"pool math is {pool_math}, expected {cfg.math}")
    if cfg.basis_coins is not None:
        basis = boa.loads_partial(BASIS_POOL_STUB).at(cfg.basis_pool)
        coins = (basis.coins(0), basis.coins(1))
        if tuple(str(c).lower() for c in coins) != tuple(c.lower() for c in cfg.basis_coins):
            raise RuntimeError(f"basis pool coins are {coins}, expected {cfg.basis_coins}")
    if tuple(policy.price_bounds()) != cfg.bounds:
        raise RuntimeError(f"price bounds are {policy.price_bounds()}, expected {cfg.bounds}")
    if policy.config() != cfg.config:
        raise RuntimeError(f"config is {policy.config()}, expected {cfg.config}")
    if policy.ratio_tolerance() != cfg.ratio_tolerance:
        raise RuntimeError(f"ratio tolerance is {policy.ratio_tolerance()}")
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
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from boa.explorer import Etherscan

    from scripts.yubi_deployers import LoadError, load_account

    cfg = CONFIG
    if not cfg.rpc_url:
        raise ValueError("ETH_RPC_URL is required")
    etherscan_api_key = os.environ.get("ETHERSCAN_API_KEY")
    if not etherscan_api_key:
        raise ValueError("ETHERSCAN_API_KEY is required to verify the policy")

    boa.set_network_env(cfg.rpc_url)
    # Traces are diagnostics only; a lagging RPC node must not abort after a mined tx.
    boa.env.suppress_debug_tt()
    if boa.env.evm.patch.chain_id != cfg.chain_id:
        raise ValueError(f"Expected chain {cfg.chain_id}, got {boa.env.evm.patch.chain_id}")
    if not cfg.bank or not boa.env.get_code(cfg.bank):
        raise ValueError("Set CONFIG.bank to a PythReportBank on this chain")

    policy_source = boa.load_partial("contracts/policies/YBOraclizedPolicy.vy")
    needs_signer = True
    if cfg.policy:
        # Boa needs a sender even for eth_call. Check the resumed policy before the
        # key is unlocked: this code and config, owned by the DAO (nothing to sign)
        # or by the deployer (its ownership transfer is due).
        boa.env.eoa = cfg.policy
        resumed = policy_source.at(cfg.policy)
        check(resumed, policy_source, cfg)
        owner = str(resumed.owner()).lower()
        if owner not in (cfg.owner.lower(), cfg.deployer.lower()):
            raise RuntimeError(f"Policy is owned by {resumed.owner()}, not the deployer or the DAO")
        needs_signer = owner != cfg.owner.lower()
    if needs_signer:
        # Touch the YubiKey, then type the keystore password. load_account refuses a
        # key file that holds any address but CONFIG.deployer, and writes nothing.
        try:
            signer = load_account(cfg.deployer)
        except LoadError as error:
            sys.exit(f"Signer not loaded: {error}")
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
