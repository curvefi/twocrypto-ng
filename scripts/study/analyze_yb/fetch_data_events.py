import csv
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from web3 import Web3
from web3mc import Multicall

from abis import twocrypto_abi


RPC_URL = os.environ.get("WEB3_PROVIDER_URL")
if not RPC_URL:
    raise RuntimeError("Set WEB3_PROVIDER_URL before running this script")

POOL_CONFIG = [
    {
        "name": "yb_wBTC",
        "address": "0xD9FF8396554A0d18B2CFbeC53e1979b7ecCe8373",
        "start_block": 23_434_000,
        "decimals": 8,
    },
    {
        "name": "yb_tBTC",
        "address": "0xf1F435B05D255a5dBdE37333C0f61DA6F69c6127",
        "start_block": 23_434_000,
        "decimals": 18,
    },
    {
        "name": "yb_cbBTC",
        "address": "0x83f24023d15d835a213df24fd309c47dAb5BEb32",
        "start_block": 23_434_000,
        "decimals": 8,
    },
]

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
    "lp_price",
    "last_prices",
    "spot_price_in",
    "spot_price_out",
)

ABI = json.loads(twocrypto_abi) if isinstance(twocrypto_abi, str) else twocrypto_abi

EVENT_NAMES = [entry.get("name", "") for entry in ABI if entry.get("type") == "event"]

MAX_WORKERS = 150
SAVE_EVERY = 25
LOG_CHUNK = 10_000

WEB3 = Web3(Web3.HTTPProvider(RPC_URL))
LATEST_BLOCK = WEB3.eth.get_block("latest")["number"]

MULTICALL_OPTIONS = {
    "provider_url": RPC_URL,
    "batch": 100,
    "max_retries": 3,
    "gas_limit": 50_000_000,
    "_semaphore": 500,
}

DATA_DIR = Path(__file__).resolve().parent / "data_events"

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
        contract = WEB3.eth.contract(address=address, abi=ABI)
        contracts.append(contract)
        pool_info[address] = {"start_block": pool["start_block"], "decimals": pool["decimals"]}

        for fn_name in FUNCTION_NAMES:
            if fn_name == "balances_0":
                call = contract.functions.balances(0)
            elif fn_name == "balances_1":
                call = contract.functions.balances(1)
            elif fn_name == "spot_price_in":  # trade 1 usd in
                call = contract.functions.get_dy(0, 1, 10**18)
            elif fn_name == "spot_price_out":  # trade 1e-5 btc in
                call = contract.functions.get_dy(
                    1, 0, int(1e-5 * 10 ** pool_info[address]["decimals"])
                )
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


def collect_event_blocks(contract, start_block):
    if start_block > LATEST_BLOCK:
        return set()

    address = contract.address
    block_numbers = set()

    chunk_size = LOG_CHUNK
    current = start_block

    while current <= LATEST_BLOCK:
        chunk_end = min(current + chunk_size - 1, LATEST_BLOCK)
        params = {
            "address": address,
            "fromBlock": current,
            "toBlock": chunk_end,
        }

        logs = WEB3.eth.get_logs(params)

        for log in logs:
            block = log["blockNumber"]
            block_numbers.add(block)
            # add preceding block (for decaying values checkpointing)
            if block - 1 >= start_block:
                block_numbers.add(block - 1)
            # add sparse future blocks (for nonlinear values like ema oracle)
            for future_delta in [25, 50, 100]:
                if block + future_delta <= LATEST_BLOCK:
                    block_numbers.add(block + future_delta)

        current = chunk_end + 1

    block_numbers.add(LATEST_BLOCK)
    return block_numbers


def compute_event_starts(results, use_latest=True):
    starts = {}
    for contract in CONTRACTS:
        base_start = POOL_INFO[contract.address]["start_block"]
        pool_blocks = results.get(contract.address, {})
        if pool_blocks and use_latest:
            last_recorded = max(pool_blocks)
            starts[contract.address] = max(base_start, last_recorded + 1)
        else:
            starts[contract.address] = base_start
    return starts


def gather_blocks(event_starts):
    combined = set()

    for contract in CONTRACTS:
        combined.add(POOL_INFO[contract.address]["start_block"])
        start_block = event_starts.get(contract.address, POOL_INFO[contract.address]["start_block"])
        blocks = collect_event_blocks(contract, start_block)
        combined.update(blocks)
        print(
            f"Pool {contract.address}: {len(blocks)} candidate blocks starting from block {start_block}"
        )

    filtered = sorted(block for block in combined if block <= LATEST_BLOCK)
    return filtered


def block_needs_fetch(block, results):
    for pool_address, info in POOL_INFO.items():
        if block < info["start_block"]:
            continue
        pool_blocks = results.get(pool_address, {})
        if block not in pool_blocks or pool_blocks[block].get("timestamp") in (None, ""):
            return True
    return False


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


CONTRACTS, CALLS, CALL_ADDRESSES, CALL_METADATA, POOL_INFO = prepare_calls()


def main():
    print(f"Tracking events: {', '.join(EVENT_NAMES)}")

    existing_data = load_existing_data()
    results = {
        contract.address: dict(existing_data.get(contract.address, {})) for contract in CONTRACTS
    }

    event_starts = compute_event_starts(results, use_latest=True)

    target_blocks = gather_blocks(event_starts)

    missing_blocks = [block for block in target_blocks if block_needs_fetch(block, results)]
    total_missing = len(missing_blocks)

    if not total_missing:
        print("No missing blocks detected. Nothing to fetch.")
        write_all_csv(results)
        return

    print(f"Fetching {total_missing} event-driven blocks (latest target {LATEST_BLOCK})")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_block, block, CALLS, CALL_ADDRESSES): block
            for block in missing_blocks
        }

        completed = 0
        for future in as_completed(futures):
            block_number = futures[future]
            try:
                finished_block, block_timestamp, block_payload = future.result()
            except Exception as exc:  # noqa: BLE001
                print(f"Block {block_number} failed: {exc}")
                continue

            for pool_address, pool_values in block_payload.items():
                start_block = POOL_INFO[pool_address]["start_block"]
                if finished_block < start_block:
                    continue
                results.setdefault(pool_address, {})[finished_block] = pool_values

            completed += 1

            if completed % 10 == 0 or completed == total_missing:
                print(
                    f"Processed {completed}/{total_missing} blocks (latest done: {finished_block})"
                )

            if completed % SAVE_EVERY == 0:
                write_all_csv(results)

    write_all_csv(results)
    print(f"Saved sparse event data to {DATA_DIR}")


if __name__ == "__main__":
    main()
