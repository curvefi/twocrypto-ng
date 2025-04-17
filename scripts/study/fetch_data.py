#!/usr/bin/env python3
"""
This script fetches trade data from Curve Finance API for a specified pool
and saves it in pickle format for further processing.
"""

import os
import requests
import pickle
import time
from dotenv import load_dotenv
from pathlib import Path
from web3 import Web3

# Load environment variables from .env file
load_dotenv()
TRADE_API_LINK_TEMPLATE = os.getenv("TRADE_API_LINK")
LIQ_API_LINK_TEMPLATE = os.getenv("LIQ_API_LINK")
ETH_RPC_URL = os.getenv("ETH_RPC_URL")

# Configuration - modify these values for your specific pool
CHAIN = "xdai"
POOL_ADDRESS = "0xC907ba505C2E1cbc4658c395d4a2c7E6d2c32656"  # Pool contract address
POOL_ADDRESS = Web3.to_checksum_address(POOL_ADDRESS)

PER_PAGE = 100  # Maximum number of trades per page
MAX_PAGES = 20  # Maximum number of pages to fetch (set to None for all)

# ABI for Curve pools - minimal ABI just for getting coin addresses
POOL_ABI = [
    {
        "name": "coins",
        "inputs": [{"name": "arg0", "type": "uint256"}],
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]


def get_pool_tokens():
    """
    Connect to the pool contract and get all token addresses
    """
    w3 = Web3(Web3.HTTPProvider(ETH_RPC_URL))
    if not w3.is_connected():
        raise Exception("Failed to connect to Ethereum node")

    # Create contract instance
    pool_contract = w3.eth.contract(address=w3.to_checksum_address(POOL_ADDRESS), abi=POOL_ABI)

    # Get all coins by calling coins(i) until it fails
    tokens = []
    i = 0
    while True:
        try:
            token_address = pool_contract.functions.coins(i).call()
            tokens.append(Web3.to_checksum_address(token_address))
            print(f"Found token {i}: {token_address}")
            i += 1
        except Exception as e:
            # If we get an error, we've reached the end of the coins array
            print(f"Stopped at index {i}: {e}")
            break

    return tokens


def fetch_trade_data(token_0, token_1, page=1):
    """
    Fetch trade data for a specific token pair and page
    """
    url = TRADE_API_LINK_TEMPLATE.format(
        chain=CHAIN,
        pool=POOL_ADDRESS,
        token_0=token_0,
        token_1=token_1,
        page=page,
        per_page=PER_PAGE,
    )

    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise exception for 4XX/5XX responses
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data for {token_0}/{token_1} page {page}: {e}")
        return None


def fetch_all_trade_data_for_pair(token_0, token_1):
    """
    Fetch all trade data for a specific token pair by paginating through results
    """
    all_data = []
    current_page = 1
    total_trades = 0

    print(f"Fetching trade data for {token_0}/{token_1} on {CHAIN}...")

    while True:
        if MAX_PAGES is not None and current_page > MAX_PAGES:
            print(f"Reached maximum number of pages ({MAX_PAGES})")
            break

        print(f"Fetching page {current_page}...")
        data = fetch_trade_data(token_0, token_1, current_page)

        if not data or "trades" not in data or not data["trades"]:
            print("No more trades found")
            break

        trades = data["trades"]
        all_data.extend(trades)
        total_trades += len(trades)

        print(f"Retrieved {len(trades)} trades (total: {total_trades})")

        # Check if we've reached the end of available data
        if len(trades) < PER_PAGE:
            print("Last page reached")
            break

        current_page += 1

        # Add a small delay to avoid overwhelming the API
        time.sleep(0.5)

    # Include the state information from the last response if available
    if data and "state" in data:
        metadata = {
            "state": data["state"],
            "pool": POOL_ADDRESS,
            "chain": CHAIN,
            "token_0": token_0,
            "token_1": token_1,
            "total_trades": total_trades,
        }
        all_data.append({"metadata": metadata})

    return all_data


def fetch_all_pairs_trade_data():
    """
    Fetch trade data for all token pairs with token 0 as the base
    """
    # Get all token addresses from the pool
    tokens = get_pool_tokens()

    if len(tokens) == 0:
        print("No tokens found in the pool")
        return {}

    base_token = tokens[0]  # Token 0 is our base token

    # Fetch data for each pair (base_token with each other token)
    all_pairs_data = {}

    for i in range(1, len(tokens)):
        pair_key = f"{base_token}_{tokens[i]}"
        print(f"\nFetching data for pair {pair_key}")

        pair_data = fetch_all_trade_data_for_pair(base_token, tokens[i])
        all_pairs_data[pair_key] = pair_data

        # Pause between fetching different pairs
        if i < len(tokens) - 1:
            print("Pausing before next pair...")
            time.sleep(2)

    return all_pairs_data


def fetch_all_liquidity_data():
    """
    Fetch all liquidity data for the specified pool by paginating through results
    """
    all_data = []
    current_page = 1
    total_liquidity = 0

    print(f"Fetching liquidity data for {POOL_ADDRESS} on {CHAIN}...")

    while True:
        url = LIQ_API_LINK_TEMPLATE.format(
            chain=CHAIN, pool=POOL_ADDRESS, page=current_page, per_page=PER_PAGE
        )

        try:
            if MAX_PAGES is not None and current_page > MAX_PAGES:
                print(f"Reached maximum number of pages ({MAX_PAGES})")
                break

            response = requests.get(url)
            response.raise_for_status()  # Raise exception for 4XX/5XX responses
            data = response.json()

            if not data or not data["data"]:
                print("No more liquidity data found")
                break

            liquidity = data["data"]
            all_data.extend(liquidity)
            total_liquidity += len(liquidity)

            print(f"Retrieved {len(liquidity)} liquidity (total: {total_liquidity})")

            if len(liquidity) < PER_PAGE:
                print("Last page reached")
                break

            current_page += 1

        except requests.exceptions.RequestException as e:
            print(f"Error fetching data for page {current_page}: {e}")
            break

    return all_data


def save_data_to_pickle(data, filename):
    """
    Save data to a pickle file
    """
    with open(filename, "wb") as f:
        pickle.dump(data, f)
    print(f"Data saved to {filename}")


def main():
    """
    Main function to fetch and save trade data
    """
    # Create the output directory if it doesn't exist
    output_path = Path(__file__).parent / "data"
    output_path.mkdir(exist_ok=True)

    # Fetch all pairs trade data
    all_pairs_data = fetch_all_pairs_trade_data()

    if not all_pairs_data:
        print("No trade data retrieved")
        return

    # Also save all data together
    all_output_file = output_path / f"curve_trades_{CHAIN}_{POOL_ADDRESS}_all.pickle"
    save_data_to_pickle(all_pairs_data, all_output_file)

    print(f"Process completed. All data saved to {output_path}")

    # Fetch all liquidity data
    liquidity_data = fetch_all_liquidity_data()
    if not liquidity_data:
        print("No liquidity data retrieved")
        return

    print(f"Retrieved a total of {len(liquidity_data)} liquidity")

    # Save liquidity data to pickle file
    liquidity_output_file = output_path / "curve_liquidity.pickle"
    save_data_to_pickle(liquidity_data, liquidity_output_file)


if __name__ == "__main__":
    main()
