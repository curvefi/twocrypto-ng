"""Deploy RPFController for the YieldBasis crvUSD/WETH pool and hand it to the YieldBasis DAO.

Run from the repository root: `uv run python scripts/deploy_rpf_controller.py`, with
ETH_RPC_URL and ETHERSCAN_API_KEY set; add `--dry-run` for the fork rehearsal alone,
which needs neither the key nor ETHERSCAN_API_KEY. The deployer CONFIG.deployer signs:
its key opens only with a YubiKey touch and then the keystore password
(scripts/yubi_deployers.py; the key file is ~/.config/eth/<deployer>.json.age, and `age`
and `age-plugin-yubikey` must be on PATH).

Every run first rehearses on a fork of the latest block: deploy, read every parameter
back, transfer ownership, then make the calls of the Curve DAO vote below and call
update(). Only then is the key unlocked. The deployer deploys the controller, every
parameter is read back, ownership moves to the YieldBasis DAO, and the source is verified
on Etherscan. Set CONFIG.controller to an address an interrupted run printed to resume
without redeploying; a resumed controller the DAO already owns needs no key.

The controller does nothing until a Curve DAO vote has made these calls (printed with the
deployed address at the end of a run), after any vote that still reaches the factory
through its present admin has executed:
1. factory admin (the old owner proxy).execute(factory, commit_transfer_ownership(CONFIG.proxy))
2. CONFIG.proxy.accept_transfer_ownership(factory): the proxy becomes the admin of every
   pool and gauge of the factory
3. CONFIG.proxy.set_permission(controller, pool, set_fee_parameters selector, True)
Leave update() out of the vote: it reverts when there is nothing to change. Anyone calls it
afterwards.
"""

import argparse
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import boa
from eth_abi import encode
from eth_utils import keccak

FEE_PRECISION = 10**10
BP = 10**14  # one basis point as a gap (1e18 = 100%)

CONFIG = SimpleNamespace(
    rpc_url=os.environ.get("ETH_RPC_URL"),
    chain_id=1,
    pool="0x656341Ef90b622c6634e0573772FfB7f3669b9f3",  # YieldBasis crvUSD/WETH (market 10)
    factory="0x98EE851a00abeE0d95D08cF4CA2BdCE32aeaAF7F",  # the pool's factory (checked)
    # UnifiedOwnerProxy (edao-proxy, 2026-11-26): the factory's admin once the vote has executed
    proxy="0xeDA010c47aeF0574fe98D02B0de3648f81Daf149",
    owner="0x42F2A41A0D0e65A440813190880c8a65124895Fa",  # YieldBasis DAO
    # The YubiKey-held key ~/.config/eth/<deployer>.json.age signs the deployment.
    deployer="0xb101b2b0aa02b7167D238B98dc1B0b0404a760E8",
    # Config(baseline_rpf, harvest_gap, restore_gap, min_change_period), owner-settable.
    # The baseline is the pool's present RPF (checked): 43%. Gaps 40 and 20 bp, 10 minutes.
    config=(43 * FEE_PRECISION // 100, 40 * BP, 20 * BP, 600),
    controller=None,  # Resume: the address of an earlier deployment.
)

SET_FEE_PARAMETERS = keccak(text="set_fee_parameters(uint256,uint256)")[:4]

# ABI stubs for check() and the rehearsal.
POOL_STUB = """
@external
@view
def factory() -> address:
    return empty(address)

@external
@view
def admin() -> address:
    return empty(address)

@external
@view
def reserved_profit_fraction() -> uint256:
    return 0

@external
@view
def admin_fee() -> uint256:
    return 0
"""
PROXY_STUB = """
@external
@view
def dao() -> address:
    return empty(address)

@external
@view
def permissions(controller: address, target: address, selector: bytes4) -> bool:
    return False
"""


def same(a, b):
    return str(a).lower() == str(b).lower()


def check(controller, source, cfg):
    """Raise unless the deployed code and every parameter match CONFIG."""
    runtime = controller.bytecode
    if controller.data_section_size:
        runtime = runtime[: -controller.data_section_size]
    if runtime != source.compiler_data.bytecode_runtime:
        raise RuntimeError("Onchain runtime bytecode does not match the controller source")

    if not same(controller.POOL(), cfg.pool):
        raise RuntimeError(f"POOL is {controller.POOL()}, expected {cfg.pool}")
    if not same(controller.PROXY(), cfg.proxy):
        raise RuntimeError(f"PROXY is {controller.PROXY()}, expected {cfg.proxy}")
    if tuple(controller.config()) != cfg.config:
        raise RuntimeError(f"config is {controller.config()}, expected {cfg.config}")

    pool = boa.loads_partial(POOL_STUB).at(cfg.pool)
    if not same(pool.factory(), cfg.factory):
        raise RuntimeError(f"pool factory is {pool.factory()}, expected {cfg.factory}")
    # update() moves any other RPF to one of these two
    pool_rpf = pool.reserved_profit_fraction()
    if pool_rpf not in (cfg.config[0], FEE_PRECISION):
        raise RuntimeError(f"pool RPF is {pool_rpf}, neither the baseline {cfg.config[0]} nor 100%")
    # The proxy answers as an owner proxy with a controller table; the controller reads the pool
    proxy = boa.loads_partial(PROXY_STUB).at(cfg.proxy)
    permitted = proxy.permissions(controller.address, cfg.pool, SET_FEE_PARAMETERS)
    target = controller.target_rpf()
    print(
        f"Pool RPF {pool_rpf}, target {target}, admin {str(pool.admin())}, "
        f"controller permitted on the proxy: {permitted}"
    )


def deploy(source, cfg):
    """Deploy or resume, check every parameter, and transfer ownership to cfg.owner."""
    args = (cfg.pool, cfg.proxy, cfg.config)
    if cfg.controller:
        controller = source.at(cfg.controller)
        # Etherscan verification needs the constructor arguments of the deployment.
        controller.ctor_calldata = controller._ctor.prepare_calldata(*args)
        print(f"Reusing controller: {controller.address}")
    else:
        controller = source.deploy(*args)
        print(f"Controller deployed: {controller.address} (CONFIG.controller to resume)")
    check(controller, source, cfg)

    if not same(controller.owner(), cfg.owner):
        if not same(controller.owner(), boa.env.eoa):
            raise RuntimeError(f"Owned by {controller.owner()}, not the signer or the DAO")
        controller.transfer_ownership(cfg.owner)
    if not same(controller.owner(), cfg.owner):
        raise RuntimeError("Ownership transfer to the DAO did not land")
    print(f"Owner: {controller.owner()}")
    return controller


def vote_calls(controller, cfg, factory_admin):
    """(caller's target, signature, argument types, arguments) of the Curve DAO vote."""
    commit = keccak(text="commit_transfer_ownership(address)")[:4] + encode(
        ["address"], [cfg.proxy]
    )
    calls = []
    if not same(factory_admin, cfg.proxy):
        calls += [
            (factory_admin, "execute(address,bytes)", ["address", "bytes"], [cfg.factory, commit]),
            (cfg.proxy, "accept_transfer_ownership(address)", ["address"], [cfg.factory]),
        ]
    calls.append(
        (
            cfg.proxy,
            "set_permission(address,address,bytes4,bool)",
            ["address", "address", "bytes4", "bool"],
            [str(controller.address), cfg.pool, SET_FEE_PARAMETERS, True],
        )
    )
    return calls


def rehearse_vote(controller, cfg):
    """On a fork: the vote's calls as the Curve DAO, then update() as a stranger."""
    pool = boa.loads_partial(POOL_STUB).at(cfg.pool)
    curve_dao = boa.loads_partial(PROXY_STUB).at(cfg.proxy).dao()
    admin_fee = pool.admin_fee()
    for target, signature, types, args in vote_calls(controller, cfg, pool.admin()):
        data = keccak(text=signature)[:4] + encode(types, args)
        boa.env.raw_call(target, sender=curve_dao, data=data)
    if not same(pool.admin(), cfg.proxy):
        raise RuntimeError(f"After the vote the pool's admin is {pool.admin()}")
    proxy = boa.loads_partial(PROXY_STUB).at(cfg.proxy)
    if not proxy.permissions(controller.address, cfg.pool, SET_FEE_PARAMETERS):
        raise RuntimeError("After the vote the proxy does not permit the controller")

    target = controller.target_rpf()
    if target == pool.reserved_profit_fraction():
        with boa.reverts("no change"):
            controller.update()
    else:
        controller.update(sender=boa.env.generate_address())
    if pool.reserved_profit_fraction() != target or pool.admin_fee() != admin_fee:
        raise RuntimeError("update() did not set the target RPF with the admin fee kept")
    print(f"After the vote: update() leaves the pool at RPF {target}, admin fee {admin_fee}")


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.yubi_deployers import LoadError, load_account

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="fork rehearsal only, no key")
    dry_run = parser.parse_args().dry_run

    cfg = CONFIG
    if not cfg.rpc_url:
        raise ValueError("ETH_RPC_URL is required")
    etherscan_api_key = os.environ.get("ETHERSCAN_API_KEY")
    if not dry_run and not etherscan_api_key:
        raise ValueError("ETHERSCAN_API_KEY is required to verify the controller")
    source = boa.load_partial("contracts/policies/RPFController.vy")

    # Rehearsal on a fork of the latest block, sending as the deployer without its key.
    with boa.fork(cfg.rpc_url, block_identifier="latest", allow_dirty=True):
        if boa.env.evm.patch.chain_id != cfg.chain_id:
            raise ValueError(f"Expected chain {cfg.chain_id}, got {boa.env.evm.patch.chain_id}")
        boa.env.eoa = cfg.deployer
        rehearse_vote(deploy(source, cfg), cfg)
    print("Fork rehearsal passed")
    if dry_run:
        return

    boa.set_network_env(cfg.rpc_url)
    # Traces are diagnostics only; a lagging RPC node must not abort after a mined tx.
    boa.env.suppress_debug_tt()
    if boa.env.evm.patch.chain_id != cfg.chain_id:
        raise ValueError(f"Expected chain {cfg.chain_id}, got {boa.env.evm.patch.chain_id}")
    needs_signer = True
    if cfg.controller:
        # Boa needs a sender even for eth_call. Read the resumed controller's owner on
        # the live chain before the key is unlocked: the DAO (nothing to sign) or the
        # deployer (its ownership transfer is due).
        boa.env.eoa = cfg.controller
        owner = source.at(cfg.controller).owner()
        if not same(owner, cfg.owner) and not same(owner, cfg.deployer):
            raise RuntimeError(f"Controller is owned by {owner}, not the deployer or the DAO")
        needs_signer = not same(owner, cfg.owner)
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
    controller = deploy(source, cfg)

    from boa.explorer import Etherscan

    try:
        verifier = Etherscan(api_key=etherscan_api_key, chain_id=cfg.chain_id)
        boa.verify(controller, verifier=verifier, wait=True)
        print(f"Verified: https://etherscan.io/address/{controller.address}#code")
    except Exception as exc:  # The onchain steps are done; only verification needs a retry.
        print(f"Verification failed: {exc}. Rerun with CONFIG.controller set.")

    print("Curve DAO vote, in this order:")
    factory_admin = boa.loads_partial(POOL_STUB).at(cfg.pool).admin()
    for target, signature, _, args in vote_calls(controller, cfg, factory_admin):
        shown = [("0x" + a.hex() if isinstance(a, bytes) else a) for a in args]
        print(f"  {str(target)}.{signature} {shown}")


if __name__ == "__main__":
    main()
