#!/usr/bin/env python3

import asyncio
import aiohttp
from web3 import AsyncWeb3, AsyncHTTPProvider
import matplotlib.pyplot as plt
from dotenv import load_dotenv
import os
import numpy as np
import json
from typing import List, Dict, Any, Tuple, Set, Optional
import pickle
from pathlib import Path

# Load environment variables early
load_dotenv()

# Contract view functions to fetch
# Format: (function_name, [arg1, arg2, ...])
FUNCTIONS_TO_FETCH = [
    ("xcp_profit", []),
    ("xcp_profit_a", []),
    ("price_scale", [0]),
    ("price_scale", [1]),
    ("price_oracle", [0]),
    ("price_oracle", [1]),
    ("virtual_price", []),
    ("D", []),
]


# Cache paths and operations
def get_cache_path(cache_dir: str, contract_address: str) -> Path:
    """Get the path to the cache file for a specific contract"""
    return Path(cache_dir) / f"{contract_address.lower()}_state.pkl"


def load_cached_data(
    cache_dir: str, contract_address: str
) -> Dict[int, Dict[Tuple[str, Tuple], Any]]:
    """Load blockchain data from cache
    Returns a dict with {block_number: {(func_name, args): value}}"""
    cache_path = get_cache_path(cache_dir, contract_address)
    if cache_path.exists():
        with open(cache_path, "rb") as f:
            return pickle.load(f)
    return {}


def save_cached_data(
    cache_dir: str, contract_address: str, data: Dict[int, Dict[Tuple[str, Tuple], Any]]
):
    """Save blockchain data to cache file"""
    cache_path = get_cache_path(cache_dir, contract_address)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "wb") as f:
        pickle.dump(data, f)


async def get_etherscan_abi(
    contract_address: str, chain_id: int = 1, cache_dir: Optional[str] = None
) -> List[Dict]:
    """Fetch contract ABI from Etherscan, with caching"""
    if cache_dir:
        cache_file = Path(cache_dir) / f"{contract_address.lower()}.abi"
        os.makedirs(cache_dir, exist_ok=True)

        if cache_file.exists():
            with open(cache_file, "r") as f:
                return json.load(f)

    # Fetch from Etherscan
    api_key = os.getenv("ETHERSCAN_API_KEY")
    url = (
        f"https://api.etherscan.io/v2/api?chainid={chain_id}"
        f"&module=contract&action=getabi&address={contract_address}"
        f"&apikey={api_key}"
    )

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            result = (await response.json())["result"]

    abi_data = json.loads(result)

    # Cache the result
    if cache_dir:
        with open(cache_file, "w") as f:
            json.dump(abi_data, f, indent=4)

    return abi_data


async def fetch_missing_contract_data(
    w3: AsyncWeb3,
    contract,
    blocks_to_functions: Dict[int, List[Tuple[str, List]]],
    cached_data: Dict[int, Dict[Tuple[str, Tuple], Any]],
    cache_dir: str,
    batch_size: int = 10,
    delay_between_batches: float = 1.0,
) -> Set[int]:
    """Fetch missing contract data in batches and update cache
    Returns set of completed blocks"""

    if not blocks_to_functions:
        return set()

    all_blocks = sorted(blocks_to_functions.keys())
    completed_blocks = set()

    print(f"Fetching data for {len(all_blocks)} blocks from chain... (batch size: {batch_size})")

    # Process in batches
    for i in range(0, len(all_blocks), batch_size):
        batch_blocks = all_blocks[i : i + batch_size]
        batch_calls = []

        # Create call tasks for this batch
        for block in batch_blocks:
            for func_name, args in blocks_to_functions[block]:
                try:
                    func = getattr(contract.functions, func_name)
                    call = func(*args).call(block_identifier=int(block))
                    batch_calls.append((block, func_name, tuple(args), call))
                except Exception as e:
                    print(f"Warning: Failed to call {func_name}{args} at block {block}: {str(e)}")
                    continue

        # Execute all calls
        results = await asyncio.gather(*[call[3] for call in batch_calls], return_exceptions=True)
        print(results)
        # Update cache
        for (block, func_name, args, _), result in zip(batch_calls, results):
            if not isinstance(result, Exception):
                # Initialize block cache if needed
                if block not in cached_data:
                    cached_data[block] = {}

                # Save result
                cached_data[block][(func_name, args)] = result

                # Mark block as completed if all functions are fetched
                if all(
                    (func, tuple(a)) in cached_data[block] for func, a in blocks_to_functions[block]
                ):
                    completed_blocks.add(block)

        # Save progress
        save_cached_data(cache_dir, contract.address.lower(), cached_data)
        print(f"Progress: {len(completed_blocks)}/{len(all_blocks)} blocks completed")

        # Delay to avoid overloading RPC
        await asyncio.sleep(delay_between_batches)

    return completed_blocks


async def get_contract_views(
    w3: AsyncWeb3,
    contract,
    blocks: List[int],
    cache_dir: str,
    batch_size: int = 100,
    delay_between_batches: float = 1.0,
) -> Dict[str, Dict[int, Any]]:
    """Get all contract view function values for blocks, using cache when available"""

    # Load cache
    cached_data = load_cached_data(cache_dir, contract.address.lower())

    # Identify missing data for each block
    blocks_to_functions = {}

    for block in blocks:
        missing_functions = []

        if block not in cached_data:
            # All functions are missing for this block
            missing_functions = FUNCTIONS_TO_FETCH.copy()
        else:
            # Check which functions are missing
            for func_name, args in FUNCTIONS_TO_FETCH:
                if (func_name, tuple(args)) not in cached_data[block]:
                    missing_functions.append((func_name, args))

        if missing_functions:
            blocks_to_functions[block] = missing_functions

    # Fetch missing data
    if blocks_to_functions:
        await fetch_missing_contract_data(
            w3,
            contract,
            blocks_to_functions,
            cached_data,
            cache_dir,
            batch_size,
            delay_between_batches,
        )

    # Build result structure
    state = {}
    for func_name, args in FUNCTIONS_TO_FETCH:
        # Create human-readable key
        key = func_name if not args else f"{func_name}{args}"
        cache_key = (func_name, tuple(args))

        # Map block -> value for this function
        state[key] = {block: cached_data.get(block, {}).get(cache_key) for block in blocks}

    return state


async def fetch_contract_data(
    w3: AsyncWeb3,
    contract,
    blocks: List[int],
    cache_dir: str,
    batch_size: int = 10,
    delay_between_batches: float = 1.0,
) -> List[Dict]:
    """Fetch contract data for blocks and return as a list of block results"""
    # Get contract views
    state = await get_contract_views(
        w3, contract, blocks, cache_dir, batch_size, delay_between_batches
    )

    # Build results
    return [{"block": block, "state": {k: v[block] for k, v in state.items()}} for block in blocks]


async def main():
    print("Initializing Web3 connection...")

    # Initialize Web3
    w3 = AsyncWeb3(AsyncHTTPProvider(os.getenv("ETH_RPC_URL")))
    # w3 = AsyncWeb3(AsyncHTTPProvider('https://mainnet.chainsland.xyz'))

    # Get block range to analyze
    print("Fetching current block number...")
    now = await w3.eth.block_number
    now = 22_222_222
    past = now - 86_400 * 30 // 12  # 1 year back
    blocks = np.arange(past, now, 100, dtype=int)
    print(f"Analyzing blocks {past} to {now}")
    past = 12821149
    blocks = np.arange(past, now, 10000, dtype=int)
    blocks = blocks[2:]
    # Constants
    contract_address = "0xD51a44d3FaE010294C616388b506AcdA1bfAAE46"
    cache_dir = "scripts/study/data/state_cache"

    # Get contract ABI
    print("Fetching contract ABI...")
    abi = await get_etherscan_abi(contract_address, cache_dir="scripts/study/data/cache")

    # Initialize contract
    contract = w3.eth.contract(address=contract_address, abi=abi)

    # Print functions we're fetching
    print("Functions to fetch:")
    for func_name, args in FUNCTIONS_TO_FETCH:
        print(f"  - {func_name}{args}")

    # Fetch data
    print(f"Fetching data for {len(blocks)} blocks...")
    results = await fetch_contract_data(
        w3, contract, blocks, cache_dir, batch_size=50, delay_between_batches=1.0
    )

    # Extract data for plotting
    block_numbers = np.array([r["block"] for r in results])
    xcp_profit = np.array([r["state"]["xcp_profit"] / 1e18 for r in results])
    xcp_profit_a = np.array([r["state"]["xcp_profit_a"] / 1e18 for r in results])
    xcpx = (xcp_profit + xcp_profit_a) / 2

    vp = np.array([r["state"]["virtual_price"] / 1e18 for r in results])
    # Plot results
    print("Plotting results...")
    plt.figure(figsize=(10, 6))
    plt.plot(
        block_numbers, (xcp_profit - 1) / 2 + 1, c="red", markersize=1, label="(xcp_profit-1)/2+1"
    )
    plt.plot(
        block_numbers,
        (xcp_profit_a - 1) / 2 + 1,
        c="green",
        markersize=1,
        label="(xcp_profit_a-1)/2+1",
    )
    plt.plot(
        block_numbers,
        (xcpx - 1) / 2 + 1,
        c="blue",
        markersize=1,
        label="(xcp_profit + xcp_profit_a - 2)/4+1",
    )
    plt.plot(block_numbers, vp, c="orange", markersize=1, label="virtual_price-1")

    plt.title("XCP Values over Blocks")
    plt.xlabel("Block Number")
    plt.ylabel("XCP Value")
    plt.legend()
    plt.grid(True, linestyle="--", alpha=0.7)

    # Format x-axis to show full integers without scientific notation
    ax = plt.gca()
    ax.get_xaxis().set_major_formatter(plt.FuncFormatter(lambda x, loc: "{:,}".format(int(x))))
    plt.xticks(rotation=30)

    print(f"Block span: {block_numbers[-1] - block_numbers[0]}")

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    asyncio.run(main())
