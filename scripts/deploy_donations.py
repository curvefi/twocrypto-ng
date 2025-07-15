import boa
import os
from eth_account import Account
from boa.explorer import Etherscan
from eth_utils import keccak

rpc_url = "https://bsc-testnet.drpc.org"
etherscan_api_key = os.environ.get("ETHERSCAN_API_KEY")

private_key = os.environ.get("WEB3_TESTNET_PK")
if not private_key:
    raise ValueError("WEB3_TESTNET_PK not found in environment")
deployer = Account.from_key(private_key)

# Setup boa environment
boa.set_network_env(rpc_url)
boa.env.add_account(deployer)
boa.env.eoa = deployer.address

print(
    f"Chain: {boa.env.evm.patch.chain_id}, Deployer: {deployer.address}, Balance: {boa.env.get_balance(deployer.address)/1e18} BNB"
)

# load contracts
math_deployer = boa.load_partial("contracts/main/StableswapMath.vy")
views_deployer = boa.load_partial("contracts/main/TwocryptoView.vy")
twocrypto_deployer = boa.load_partial("contracts/main/Twocrypto.vy")

# deploy as blueprints
DEPLOY = False
if DEPLOY:
    math_contract = math_deployer.deploy()
    views_contract = views_deployer.deploy()
    twocrypto_contract = twocrypto_deployer.deploy_as_blueprint()
else:
    math_contract = math_deployer.at("0xFEFc85c68563f7A940b4E1A9Fa8c14913b1dacdD")
    views_contract = views_deployer.at("0x91497DCA36EdE8BF1c0C4f397C5D627A733AbfE9")
    twocrypto_contract = twocrypto_deployer.at("0x13dA609dC0dE714F8F92f13438eDB0da6B39c88d")

print(f"Math: {math_contract.address}")
print(f"Views: {views_contract.address}")
print(f"Twocrypto: {twocrypto_contract.address}")

# verify contracts
etherscan_url = "https://api.etherscan.io/v2/api?chainid=" + str(boa.env.evm.patch.chain_id)
boa.set_etherscan(etherscan_url, etherscan_api_key)
verifier = Etherscan(etherscan_url, etherscan_api_key)

for contract in [math_contract, views_contract, twocrypto_contract]:
    contract.ctor_calldata = b""
    try:
        boa.verify(contract, verifier=verifier)
    except Exception as e:
        print(e)

# get factory
factory = boa.from_etherscan("0x2AF43209B366A4491CCe0A97C5a7B6059fd21295")
print(factory.admin())

# set pool implementation
pool_id = int(keccak(text="fx").hex(), 16)
print("Implementation ID:", pool_id)
factory.set_pool_implementation(twocrypto_contract.address, pool_id, sender=deployer.address)

# # set pool periphery
# pool = boa.from_etherscan("0x2433dcdc7770170bf135b7ee9ed88faa69d6d4ce")
# pool.set_periphery(twocrypto_contract.address, sender=deployer.address)
