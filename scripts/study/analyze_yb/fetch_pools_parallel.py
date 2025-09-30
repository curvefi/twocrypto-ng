import csv
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from web3 import Web3
from web3mc import Multicall

from twocrypto_abi import abi


RPC_URL = os.environ.get("WEB3_PROVIDER_URL")
RPC_URL = "https://lb.drpc.org/ethereum/AohYxdoKok53iRKt2O9xAcVOR6FEf6sR7aqHAkKsEQAD"
RPC_URL = "https://lb.drpc.org/ethereum/AjChmXR1REONnrj1N60gVt9WYwvIkzcR8LjVwg8TMB_n"
if not RPC_URL:
    raise RuntimeError("Set WEB3_PROVIDER_URL before running this script")

# Pool configuration lives up here so tweaking addresses or start blocks is easy.
POOL_CONFIG = [
    {
        "name": "yb_wBTC",
        "address": "0xD9FF8396554A0d18B2CFbeC53e1979b7ecCe8373",
        "start_block": 23_434_000,
    },
    {
        "name": "yb_tBTC",
        "address": "0xf1F435B05D255a5dBdE37333C0f61DA6F69c6127",
        "start_block": 23_434_000,
    },
    {
        "name": "yb_cbBTC",
        "address": "0x83f24023d15d835a213df24fd309c47dAb5BEb32",
        "start_block": 23_434_000,
    },
]

# Calls we read from each pool every block.
FUNCTION_NAMES = (
    "virtual_price",
    "xcp_profit",
    "price_scale",
    "price_oracle",
    "donation_shares",
    "totalSupply",
    "last_donation_release_ts",
    "donation_protection_expiry_ts",
    "balances_0",
    "balances_1",
    "D",
)

# Parallel tuning knobs.
MAX_WORKERS = 50
SAVE_EVERY = 50  # write progress to disk every N finished blocks

WEB3 = Web3(Web3.HTTPProvider(RPC_URL))
LATEST_BLOCK = WEB3.eth.get_block("latest")["number"]
BLOCK_START = min(pool["start_block"] for pool in POOL_CONFIG)
BLOCK_END = LATEST_BLOCK
BLOCK_STEP = 1

# Multicall options; tweak if RPC complains.
MULTICALL_OPTIONS = {
    "provider_url": RPC_URL,
    "batch": 100,
    "max_retries": 3,
    "gas_limit": 50_000_000,
    "_semaphore": 500,
}

DATA_DIR = Path(__file__).resolve().parent / "data"

thread_local = threading.local()


def checksum(address):
    return Web3.to_checksum_address(address)


def get_thread_multicall():
    multicall = getattr(thread_local, "multicall", None)
    if multicall is None:
        thread_local.multicall = Multicall(**MULTICALL_OPTIONS)
        multicall = thread_local.multicall
    return multicall


def prepare_calls():
    contracts = []
    calls = []
    addresses = []
    metadata = []
    pool_info = {}

    for pool in POOL_CONFIG:
        address = checksum(pool["address"])
        contract = WEB3.eth.contract(address=address, abi=abi)
        contracts.append(contract)
        pool_info[address] = {"start_block": pool["start_block"]}

        for fn_name in FUNCTION_NAMES:
            if fn_name == "balances_0":
                call = getattr(contract.functions, "balances")(0)
            elif fn_name == "balances_1":
                call = getattr(contract.functions, "balances")(1)
            else:
                call = getattr(contract.functions, fn_name)()
            calls.append(call)
            addresses.append(address)
            metadata.append((address, fn_name))

    return contracts, calls, addresses, metadata, pool_info


def load_existing_data():
    data = {}

    for contract in CONTRACTS:
        address = contract.address
        csv_path = DATA_DIR / f"{address}.csv"

        pool_data = {}

        if not csv_path.exists():
            data[address] = pool_data
            continue

        try:
            with csv_path.open(newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    block_str = row.get("block")
                    if not block_str:
                        continue
                    try:
                        block_number = int(block_str)
                    except ValueError:
                        continue

                    payload = {}
                    timestamp_str = row.get("timestamp")
                    if timestamp_str not in (None, ""):
                        try:
                            payload["timestamp"] = int(timestamp_str)
                        except ValueError:
                            payload["timestamp"] = timestamp_str
                    else:
                        payload["timestamp"] = None
                    for fn_name in FUNCTION_NAMES:
                        payload[fn_name] = row.get(fn_name)
                    pool_data[block_number] = payload

                data[address] = pool_data
        except OSError as err:
            print(f"Could not read {csv_path}: {err}")
            data[address] = pool_data

    return data


def compute_missing_blocks(results):
    missing = set()

    for pool_address, info in POOL_INFO.items():
        start_block = info["start_block"]
        pool_blocks = results.get(pool_address, {})

        for block in range(start_block, BLOCK_END + 1, BLOCK_STEP):
            if block not in pool_blocks:
                missing.add(block)

    return sorted(missing)


def fetch_block(block_number, calls, addresses):
    multicall = get_thread_multicall()
    result = multicall.aggregate(
        calls, use_try=True, addresses=addresses, block_identifier=block_number
    )
    block_info = WEB3.eth.get_block(block_number)
    block_timestamp = int(block_info["timestamp"])

    block_data = {}
    return block_number, block_timestamp, build_block_payload(result, block_timestamp, block_data)


def build_block_payload(result, block_timestamp, block_data):
    for value, (pool_address, fn_name) in zip(result, CALL_METADATA):
        pool_entry = block_data.setdefault(pool_address, {})
        pool_entry[fn_name] = value
        pool_entry["timestamp"] = block_timestamp
    return block_data


CONTRACTS, CALLS, CALL_ADDRESSES, CALL_METADATA, POOL_INFO = prepare_calls()


def write_all_csv(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    header = ["block", "timestamp", *FUNCTION_NAMES]

    for pool_address, blocks in data.items():
        csv_path = DATA_DIR / f"{pool_address}.csv"
        with csv_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=header)
            writer.writeheader()
            for block in sorted(blocks):
                payload = blocks[block]
                timestamp = payload.get("timestamp")
                row = {
                    "block": block,
                    "timestamp": "" if timestamp is None else str(timestamp),
                }
                for fn_name in FUNCTION_NAMES:
                    value = payload.get(fn_name)
                    if isinstance(value, bytes):
                        value = value.hex()
                    row[fn_name] = "" if value is None else str(value)
                writer.writerow(row)


def main():
    existing_data = load_existing_data()
    results = {
        contract.address: dict(existing_data.get(contract.address, {})) for contract in CONTRACTS
    }

    for contract in CONTRACTS:
        pool_blocks = results[contract.address]
        if pool_blocks:
            highest = max(pool_blocks)
            lowest = min(pool_blocks)
            print(
                f"Pool {contract.address}: {len(pool_blocks)} blocks stored ({lowest} -> {highest})"
            )
        else:
            print(f"Pool {contract.address}: no cached data yet")

    blocks = compute_missing_blocks(results)
    total_blocks = len(blocks)
    if not total_blocks:
        print("Data already covers the latest block, nothing to fetch")
        write_all_csv(results)
        return

    print(f"Fetching {total_blocks} missing blocks (newest target {BLOCK_END})")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_block, block, CALLS, CALL_ADDRESSES): block for block in blocks
        }

        completed = 0
        for future in as_completed(futures):
            block_number = futures[future]
            try:
                finished_block, block_timestamp, block_payload = future.result()
            except Exception as exc:  # noqa: BLE001 - logging the failure is enough here
                print(f"Block {block_number} failed: {exc}")
                continue

            for pool_address, pool_values in block_payload.items():
                start_block = POOL_INFO[pool_address]["start_block"]
                if finished_block < start_block:
                    continue
                results[pool_address][finished_block] = pool_values

            completed += 1

            if completed % 10 == 0 or completed == total_blocks:
                print(
                    f"Processed {completed}/{total_blocks} blocks (latest done: {finished_block})"
                )

            if completed % SAVE_EVERY == 0:
                write_all_csv(results)

    write_all_csv(results)
    print(f"Saved data to {DATA_DIR}")


if __name__ == "__main__":
    main()
