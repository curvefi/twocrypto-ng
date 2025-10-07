import os
import json
from dataclasses import dataclass
from typing import Dict, List, Tuple

from web3 import Web3
from web3.types import BlockIdentifier
from web3mc import Multicall

from abis import lt_abi  # local file in this folder
from decimal import Decimal, getcontext

# increase decimal precision for exact scaling and sums
getcontext().prec = 60


# --------------------------- Configuration ---------------------------------

# LT vaults per pool name
LT_POOLS: Dict[str, str] = {
    "yb_cbBTC": "0xD6a1147666f6E4d7161caf436d9923D44d901112",
    "yb_wBTC": "0x6095a220C5567360d459462A25b1AD5aEAD45204",
    "yb_tBTC": "0x2B513eBe7070Cff91cf699a0BFe5075020C732FF",
}

# Default scan start block (override with env LT_START_BLOCK or LT_START_BLOCK_<POOL>)
DEFAULT_START_BLOCK = int(os.environ.get("LT_START_BLOCK", 23_434_000))

# Multicall options (mirrors fetch_data_events.py style, simplified)
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


# Token decimals per LT pool
DECIMALS: Dict[str, int] = {
    "yb_cbBTC": 8,
    "yb_wBTC": 8,
    "yb_tBTC": 18,
}


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
    """Return mapping owner->UserAgg and latest scanned block (int)."""
    contract = w3.eth.contract(address=checksum(pool_addr), abi=json.loads(lt_abi))

    latest_block = w3.eth.get_block("latest")["number"] if to_block == "latest" else int(to_block)  # type: ignore[arg-type]
    start_block = int(start_block)
    decimals = DECIMALS.get(pool_name, 18)

    dep_logs = fetch_event_logs_chunked(
        contract.events.Deposit(), start_block, latest_block, LOG_CHUNK
    )
    wd_logs = fetch_event_logs_chunked(
        contract.events.Withdraw(), start_block, latest_block, LOG_CHUNK
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

    return aggs, latest_block


def preview_withdraw_many(
    w3: Web3, pool_addr: str, shares_by_owner: Dict[str, int]
) -> Dict[str, int]:
    """Use multicall to preview_withdraw for each owner with net shares > 0."""
    contract = w3.eth.contract(address=checksum(pool_addr), abi=json.loads(lt_abi))
    multicall = Multicall(**MULTICALL_OPTIONS)

    calls, addresses, owners = [], [], []
    for owner, shares in shares_by_owner.items():
        calls.append(contract.functions.preview_withdraw(int(shares)))
        addresses.append(contract.address)
        owners.append(owner)

    if not calls:
        return {}

    results = multicall.aggregate(
        calls, use_try=True, addresses=addresses, block_identifier="latest"
    )

    out: Dict[str, int] = {}
    for owner, value in zip(owners, results):
        # value may be None if call reverted; treat as 0
        try:
            out[owner] = int(value) if value is not None else 0
        except Exception:
            out[owner] = 0
    return out


def main():
    w3 = get_w3()
    abi = json.loads(lt_abi)
    print(f"Loaded LT ABI with events: {[e['name'] for e in abi if e.get('type')=='event']}")

    all_rows: List[Dict] = []

    for pool_name, addr in LT_POOLS.items():
        start_block = get_pool_start_block(pool_name)
        print(f"\nPool {pool_name} @ {checksum(addr)} | scanning from block {start_block} ...")

        aggs, latest = gather_user_aggregates(w3, pool_name, addr, start_block, to_block="latest")
        print(f"  Found {len(aggs)} unique owners with activity (latest block {latest}).")

        shares_by_owner = {owner: a.net_shares() for owner, a in aggs.items() if a.net_shares() > 0}
        print(f"  Previewing withdraw for {len(shares_by_owner)} owners with net shares > 0 ...")

        est_assets_now = preview_withdraw_many(w3, addr, shares_by_owner)
        decimals = DECIMALS.get(pool_name, 18)
        factor = Decimal(10) ** decimals

        # Build rows
        for owner, agg in aggs.items():
            net_shares = agg.net_shares()
            unrealized_assets_norm = (
                Decimal(int(est_assets_now.get(owner, 0))) / factor
                if net_shares > 0
                else Decimal(0)
            )
            est_total_assets_norm = agg.withdraws_assets_norm + unrealized_assets_norm
            est_profit_norm = est_total_assets_norm - agg.deposits_assets_norm

            all_rows.append(
                {
                    "pool": pool_name,
                    "owner": owner,
                    "deposited_assets": str(agg.deposits_assets_norm),
                    "withdrawn_assets": str(agg.withdraws_assets_norm),
                    "shares_in": str(agg.shares_in),
                    "shares_out": str(agg.shares_out),
                    "net_shares": str(net_shares),
                    "est_assets_unrealized": str(unrealized_assets_norm),
                    "est_total_assets": str(est_total_assets_norm),
                    "est_profit": str(est_profit_norm),
                    "est_profit_relative": str(est_profit_norm / agg.deposits_assets_norm * 100),
                }
            )

        # Quick summary
        realized = sum(Decimal(r["withdrawn_assets"]) for r in all_rows if r["pool"] == pool_name)
        unrealized = sum(
            Decimal(r["est_assets_unrealized"]) for r in all_rows if r["pool"] == pool_name
        )
        deposited = sum(Decimal(r["deposited_assets"]) for r in all_rows if r["pool"] == pool_name)
        rel = realized + unrealized - deposited
        rel_pct = (rel / deposited * 100) if deposited != 0 else Decimal(0)
        print(
            f"  Summary: deposited={deposited} realized={realized} unrealized={unrealized} est_profit={rel} (relative={rel_pct:.4f}%)"
        )

    # Optional: write CSV
    # filepath + csv
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_csv = script_dir + "/out_data.csv"
    if out_csv:
        import csv

        header = (
            list(all_rows[0].keys())
            if all_rows
            else [
                "pool",
                "owner",
                "deposited_assets",
                "withdrawn_assets",
                "shares_in",
                "shares_out",
                "net_shares",
                "est_assets_unrealized",
                "est_total_assets",
                "est_profit",
                "est_profit_relative",
            ]
        )
        with open(out_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=header)
            w.writeheader()
            for row in all_rows:
                w.writerow(row)
        print(f"\nWrote per-user summary to {out_csv}")
    else:
        # Print top few for a quick look
        print("\nSample rows:")
        for row in all_rows[:10]:
            print(row)


if __name__ == "__main__":
    main()
