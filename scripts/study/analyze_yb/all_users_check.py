import os
import json
import csv
from dataclasses import dataclass
from typing import Dict, List, Tuple, Union

from web3 import Web3
from web3.types import BlockIdentifier
from web3mc import Multicall

from abis import lt_abi  # local file in this folder
from decimal import Decimal, getcontext

# Increase decimal precision for exact scaling and sums
getcontext().prec = 60


# --------------------------- Configuration ---------------------------------

# LT vaults per pool name (same as in all_users_check.py)
LT_POOLS: Dict[str, str] = {
    "yb_cbBTC": "0xD6a1147666f6E4d7161caf436d9923D44d901112",
    "yb_wBTC": "0x6095a220C5567360d459462A25b1AD5aEAD45204",
    "yb_tBTC": "0x2B513eBe7070Cff91cf699a0BFe5075020C732FF",
}

# Token decimals per LT pool
DECIMALS: Dict[str, int] = {
    "yb_cbBTC": 8,
    "yb_wBTC": 8,
    "yb_tBTC": 18,
}

# Default snapshot block (override with env LT_SNAPSHOT_BLOCK)
SNAPSHOT_BLOCK = int(os.environ.get("LT_SNAPSHOT_BLOCK", 23550167))  # 22pm utc

# Default scan start block (override with env LT_START_BLOCK or LT_START_BLOCK_<POOL>)
DEFAULT_START_BLOCK = int(os.environ.get("LT_START_BLOCK", 23_434_000))

# Multicall options (mirrors style in other scripts)
MULTICALL_OPTIONS = {
    "provider_url": os.environ.get("WEB3_PROVIDER_URL", ""),
    "batch": 100,
    "max_retries": 2,
    "gas_limit": 30_000_000,
}

# Chunk size for log queries to avoid provider limits
LOG_CHUNK = 10_000


@dataclass
class UserAgg:
    # normalized asset amounts (scaled by decimals)
    deposits_assets_norm: Decimal = Decimal(0)
    withdraws_assets_norm: Decimal = Decimal(0)
    shares_in: int = 0
    shares_out: int = 0

    def net_shares(self) -> int:
        return self.shares_in - self.shares_out


def checksum(address: str) -> str:
    return Web3.to_checksum_address(address)


def get_w3() -> Web3:
    rpc = os.environ.get("WEB3_PROVIDER_URL")
    if not rpc:
        raise RuntimeError("Set WEB3_PROVIDER_URL before running this script")
    return Web3(Web3.HTTPProvider(rpc))


def get_pool_start_block(pool_name: str) -> int:
    env_key = f"LT_START_BLOCK_{pool_name}"
    return int(os.environ.get(env_key, DEFAULT_START_BLOCK))


def scale_amount(raw: int, decimals: int) -> Decimal:
    # high precision division
    return Decimal(raw) / (Decimal(10) ** decimals)


def fetch_event_logs_chunked(event, start_block: int, end_block: int, chunk: int) -> List:
    logs_all: List = []
    current = start_block
    while current <= end_block:
        to_block = min(current + chunk - 1, end_block)
        logs = event.get_logs(from_block=current, to_block=to_block)
        logs_all.extend(logs)
        current = to_block + 1
    return logs_all


def gather_user_aggregates(
    w3: Web3,
    pool_name: str,
    pool_addr: str,
    start_block: int,
    to_block: BlockIdentifier,
) -> Tuple[Dict[str, UserAgg], int]:
    """Return mapping owner->UserAgg and latest scanned (int) end block.

    Scans Deposit and Withdraw events from start_block..to_block (inclusive).
    """
    contract = w3.eth.contract(address=checksum(pool_addr), abi=json.loads(lt_abi))

    end_block = w3.eth.get_block("latest")["number"] if to_block == "latest" else int(to_block)
    start_block = int(start_block)
    decimals = DECIMALS.get(pool_name, 18)

    dep_logs = fetch_event_logs_chunked(
        contract.events.Deposit(), start_block, end_block, LOG_CHUNK
    )
    wd_logs = fetch_event_logs_chunked(
        contract.events.Withdraw(), start_block, end_block, LOG_CHUNK
    )

    aggs: Dict[str, UserAgg] = {}

    for ev in dep_logs:
        owner = ev["args"].get("owner")
        if not owner:
            continue
        a = aggs.setdefault(owner, UserAgg())
        a.deposits_assets_norm += scale_amount(int(ev["args"].get("assets", 0)), decimals)
        a.shares_in += int(ev["args"].get("shares", 0))

    for ev in wd_logs:
        owner = ev["args"].get("owner")
        if not owner:
            continue
        a = aggs.setdefault(owner, UserAgg())
        a.withdraws_assets_norm += scale_amount(int(ev["args"].get("assets", 0)), decimals)
        a.shares_out += int(ev["args"].get("shares", 0))

    return aggs, end_block


def preview_withdraw_many_at(
    w3: Web3,
    pool_addr: str,
    shares_by_owner: Dict[str, int],
    block_id: Union[int, str],
) -> Dict[str, int]:
    """Use multicall to preview_withdraw for each owner at a specific block.

    Returns: mapping owner -> preview_withdraw result (raw int asset amount).
    """
    if not shares_by_owner:
        return {}

    contract = w3.eth.contract(address=checksum(pool_addr), abi=json.loads(lt_abi))
    multicall = Multicall(**MULTICALL_OPTIONS)

    calls, addresses, owners = [], [], []
    for owner, shares in shares_by_owner.items():
        if int(shares) <= 0:
            continue
        calls.append(contract.functions.preview_withdraw(int(shares)))
        addresses.append(contract.address)
        owners.append(owner)

    if not calls:
        return {}

    results = multicall.aggregate(
        calls, use_try=True, addresses=addresses, block_identifier=block_id
    )

    out: Dict[str, int] = {}
    for owner, value in zip(owners, results):
        try:
            out[owner] = int(value) if value is not None else 0
        except Exception:
            out[owner] = 0
    return out


def main():
    w3 = get_w3()
    abi = json.loads(lt_abi)
    print(f"Loaded LT ABI with events: {[e['name'] for e in abi if e.get('type')=='event']}")

    snapshot_block = SNAPSHOT_BLOCK
    print(f"Snapshot block: {snapshot_block}")

    rows: List[Dict[str, str]] = []

    for pool_name, addr in LT_POOLS.items():
        start_block = get_pool_start_block(pool_name)
        print(f"\nPool {pool_name} @ {checksum(addr)} | scanning from block {start_block}")

        # 1) Aggregates up to snapshot
        aggs_then, end_then = gather_user_aggregates(
            w3, pool_name, addr, start_block, to_block=snapshot_block
        )
        owners_then = {
            owner: agg.net_shares() for owner, agg in aggs_then.items() if agg.net_shares() > 0
        }
        print(f"  Snapshot owners with shares > 0 at {snapshot_block}: {len(owners_then)}")

        # 2) Aggregates up to latest
        aggs_now, end_now = gather_user_aggregates(
            w3, pool_name, addr, start_block, to_block="latest"
        )
        owners_now = {
            owner: agg.net_shares() for owner, agg in aggs_now.items() if agg.net_shares() > 0
        }
        print(f"  Latest owners with shares > 0 at {end_now}: {len(owners_now)}")

        # 3) Preview withdraw amounts at snapshot for snapshot owners
        preview_then_raw = preview_withdraw_many_at(w3, addr, owners_then, block_id=snapshot_block)

        # 4) Preview withdraw amounts now for the SAME owner set, using current shares
        owners_now_subset = {owner: owners_now.get(owner, 0) for owner in owners_then.keys()}
        preview_now_raw = preview_withdraw_many_at(w3, addr, owners_now_subset, block_id="latest")

        decimals = DECIMALS.get(pool_name, 18)
        factor = Decimal(10) ** decimals

        # 5) Build rows per snapshot owner with requested metrics
        for owner in owners_then.keys():
            agg_now = aggs_now.get(owner, UserAgg())
            assets_then = int(preview_then_raw.get(owner, 0))
            assets_now = int(preview_now_raw.get(owner, 0))

            then_norm = Decimal(assets_then) / factor if assets_then else Decimal(0)
            now_norm = Decimal(assets_now) / factor if assets_now else Decimal(0)

            # Totals since inception (to latest)
            est_total_assets_norm = agg_now.withdraws_assets_norm + now_norm
            total_profit_norm = est_total_assets_norm - agg_now.deposits_assets_norm

            # Post-snapshot flows
            agg_then = aggs_then.get(owner, UserAgg())
            deposited_since_snap = agg_now.deposits_assets_norm - agg_then.deposits_assets_norm
            withdrawn_since_snap = agg_now.withdraws_assets_norm - agg_then.withdraws_assets_norm
            if deposited_since_snap < 0:
                deposited_since_snap = Decimal(0)
            if withdrawn_since_snap < 0:
                withdrawn_since_snap = Decimal(0)

            # From-snapshot profit = (current_withdrawable + withdrawn_after_snap) - (snapshot_balance + deposited_after_snap)
            from_snap_profit = (now_norm + withdrawn_since_snap) - (
                then_norm + deposited_since_snap
            )

            # Relative growth (ratios, not percents)
            snap_denom = then_norm + deposited_since_snap
            snap_rel_growth = (from_snap_profit / snap_denom) if snap_denom > 0 else Decimal(0)
            all_rel_growth = (
                (total_profit_norm / agg_now.deposits_assets_norm)
                if agg_now.deposits_assets_norm > 0
                else Decimal(0)
            )

            rows.append(
                {
                    # Requested metrics only
                    "pool": pool_name,
                    "owner": owner,
                    "deposited_assets": str(agg_now.deposits_assets_norm),
                    "withdrawn_assets": str(agg_now.withdraws_assets_norm),
                    "snapshot_balance": str(then_norm),
                    "current_withdrawable": str(now_norm),
                    "total_profit": str(total_profit_norm),
                    "from_snap_profit": str(from_snap_profit),
                    "snap_rel_growth": str(snap_rel_growth),
                    "all_rel_growth": str(all_rel_growth),
                }
            )

        # 6) Quick pool summary over the snapshot owner set
        total_then = sum(Decimal(r["snapshot_balance"]) for r in rows if r["pool"] == pool_name)
        total_now = sum(Decimal(r["current_withdrawable"]) for r in rows if r["pool"] == pool_name)
        pool_growth = total_now - total_then
        pool_growth_rel = (pool_growth / total_then) if total_then != 0 else Decimal(0)
        print(
            f"  Summary (snapshot owners): then={total_then} now={total_now} growth={pool_growth} (rel={pool_growth_rel:.6f})"
        )

    # Output CSV next to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Match the location and style of all_users_check output
    out_csv = os.path.join(script_dir, "out_data.csv")
    header = (
        list(rows[0].keys())
        if rows
        else [
            "pool",
            "owner",
            "deposited_assets",
            "withdrawn_assets",
            "snapshot_balance",
            "current_withdrawable",
            "total_profit",
            "from_snap_profit",
            "snap_rel_growth",
            "all_rel_growth",
        ]
    )

    with open(out_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"\nWrote per-user summary with requested metrics to {out_csv}")


if __name__ == "__main__":
    main()
