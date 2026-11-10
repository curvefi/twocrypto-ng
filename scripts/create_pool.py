import boa
import os
from eth_account import Account
from secure_key_utils import decrypt_private_key, getpass
from eth_utils import keccak
import math

rpc_url = os.environ.get("ETH_RPC_URL")
rpc_url = "https://bsc-dataseed.bnbchain.org"
rpc_url = "https://mainnet.base.org"
etherscan_api_key = os.environ.get("ETHERSCAN_API_KEY")


SIM = False
if not SIM:
    private_key = decrypt_private_key(os.environ.get("ENCRYPTED_PK"), getpass())
    if not private_key:
        raise ValueError("WEB3_TESTNET_PK not found in environment")
else:
    private_key = os.environ.get("WEB3_TESTNET_PK")
deployer = Account.from_key(private_key)

# Setup boa environment
if SIM:
    boa.fork(rpc_url)
else:
    boa.set_network_env(rpc_url)
    boa.env.add_account(deployer)
boa.env.eoa = deployer.address
boa.set_etherscan(api_key=etherscan_api_key)

print(
    f"Chain: {boa.env.evm.patch.chain_id}, Deployer: {deployer.address}, Balance: {boa.env.get_balance(deployer.address)/1e18}"
)

# load contracts
factory_address = "0x98EE851a00abeE0d95D08cF4CA2BdCE32aeaAF7F"  # bsc
factory_address = "0xc9Fe0C63Af9A39402e8a5514f9c43Af0322b665F"  # base
factory_contract = boa.from_etherscan(factory_address)
print(factory_contract.admin())

coin0_address = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
coin1_address = "0x18Bc5bcC660cf2B9cE3cd51a404aFe1a0cBD3C22"

params = {
    "_name": "IDRX FX DFB",
    "_symbol": "IDRX/USDC",
    "_coins": [coin0_address, coin1_address],
    "implementation_id": int(keccak(text="fx50").hex(), 16),
    "A": 500000,
    "gamma": int(10**18 * 0.001),  # irrelevant for fx pools
    "mid_fee": int(10**10 * 5 / 10_000),  # in bps
    "out_fee": int(10**10 * 50 / 10_000),  # in bps
    "fee_gamma": int(10**18 * 0.001),  # 0.003
    "allowed_extra_profit": int(10**18 * 1e-12),  # 1e-12
    "adjustment_step": int(10**18 * 1e-7),  # 1e-7
    "ma_exp_time": int(86400 / 2 / math.log(2)),  # 1h
    "initial_price": int(1 / 16603.41 * 10**18),  #
}

if SIM:
    with boa.fork(rpc_url, allow_dirty=True):
        pool_address = factory_contract.deploy_pool(**params, sender=deployer.address)
        print(f"Pool deployed to: {pool_address}")
else:
    pool_address = factory_contract.deploy_pool(**params, sender=deployer.address)
    print(f"Pool deployed to: {pool_address}")
