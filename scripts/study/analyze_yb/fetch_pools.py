from web3 import Web3
import os
from web3mc import Multicall
import json
from twocrypto_abi import abi

rpc_url = os.environ.get("WEB3_PROVIDER_URL")
w3 = Web3(Web3.HTTPProvider(rpc_url))

last_block = w3.eth.get_block("latest")

yb_wBTC = "0xD9FF8396554A0d18B2CFbeC53e1979b7ecCe8373"
yb_tBTC = "0xf1F435B05D255a5dBdE37333C0f61DA6F69c6127"
yb_cbBTC = "0x83f24023d15d835a213df24fd309c47dAb5BEb32"

wbtc_pool = w3.eth.contract(address=yb_wBTC, abi=abi)
tbbtc_pool = w3.eth.contract(address=yb_tBTC, abi=abi)
cbbtc_pool = w3.eth.contract(address=yb_cbBTC, abi=abi)

pool_arr = [wbtc_pool, tbbtc_pool, cbbtc_pool]
calls = []
addresses = []
for pool in pool_arr:
    tmp_calls = []
    tmp_calls.append(pool.functions.virtual_price())
    tmp_calls.append(pool.functions.xcp_profit())
    tmp_calls.append(pool.functions.price_scale())
    tmp_calls.append(pool.functions.price_oracle())
    tmp_calls.append(pool.functions.donation_shares())
    tmp_calls.append(pool.functions.last_donation_release_ts())
    tmp_calls.append(pool.functions.donation_protection_expiry_ts())

    tmp_addresses = [pool.address] * len(tmp_calls)
    calls.append(tmp_calls)
    addresses.append(tmp_addresses)

# flatten calls and addresses
calls = [item for sublist in calls for item in sublist]
addresses = [item for sublist in addresses for item in sublist]

block_start = 23434000
block_end = w3.eth.get_block("latest")["number"]
block_start = block_end - 10

multicall = Multicall(
    provider_url=rpc_url,  # Overrides env parameter
    batch=100,  # can lead to overflow
    max_retries=3,  # retries without use_try (aggregate function in contract)
    gas_limit=50_000_000,  # gas limit for calls
    _semaphore=1000,  # max concurrent coroutines, change carefully!
)

n_pools = len(pool_arr)
n_subcalls = len(calls) // n_pools
data = {}
for pool in pool_arr:
    data[pool.address] = {}
res_filepath = os.path.join(os.path.dirname(__file__), "pools_stats.json")
for block in range(block_start, block_end, 1):
    result = multicall.aggregate(calls, use_try=True, addresses=addresses, block_identifier=block)
    # result is now array of len 21 (7 calls for 3 pools), nust fetch in dict per pool
    for i in range(n_pools):
        pool_data = {
            "virtual_price": result[0 + i * n_subcalls],
            "xcp_profit": result[1 + i * n_subcalls],
            "price_scale": result[2 + i * n_subcalls],
            "price_oracle": result[3 + i * n_subcalls],
            "donation_shares": result[4 + i * n_subcalls],
            "last_donation_release_ts": result[5 + i * n_subcalls],
            "donation_protection_expiry_ts": result[6 + i * n_subcalls],
        }
        data[pool_arr[i].address][block] = pool_data

    if block % 1 == 0:
        print(f"Processed {block-block_start} of {block_end - block_start} blocks...")

        with open(res_filepath, "w") as f:
            json.dump(data, f, indent=4)
