import boa
import os
from eth_account import Account
from boa.explorer import Etherscan
from secure_key_utils import decrypt_private_key, getpass
import time
from eth_utils import keccak
from boa.verifiers import Blockscout

# deploy as blueprints
DEPLOY = True


def twocrypto_with_periphery(twocrypto_path, views_address, math_address):
    with open(twocrypto_path, "r") as f:
        twocrypto_code = f.read()
    twocrypto_code = twocrypto_code.replace(
        "MATH = Math(empty(address))", f"MATH = Math({math_address})", 1
    )
    twocrypto_code = twocrypto_code.replace(
        "VIEW = Views(empty(address))", f"VIEW = Views({views_address})", 1
    )
    assert f"MATH = Math({math_address})" in twocrypto_code
    assert f"VIEW = Views({views_address})" in twocrypto_code
    return boa.loads_partial(twocrypto_code)


DRPC_API_KEY = os.environ.get("DRPC_API_KEY")
# rpc_url = "https://bsc-dataseed.bnbchain.org"
rpc_url = f"https://lb.drpc.org/ogrpc?network=eth&dkey={DRPC_API_KEY}"
# rpc_url = "https://mainnet.base.org"
# rpc_url = "https://polygon-rpc.com"
# rpc_url = "https://rpc.ankr.com/etherlink_mainnet"
etherscan_api_key = os.environ.get("ETHERSCAN_API_KEY")

# private_key = os.environ.get("WEB3_TESTNET_PK")
if DEPLOY:
    private_key = decrypt_private_key(os.environ.get("ENCRYPTED_PK"), getpass())
    if not private_key:
        raise ValueError("WEB3_TESTNET_PK not found in environment")
else:
    private_key = os.environ.get("WEB3_TESTNET_PK")
deployer = Account.from_key(private_key)

# Setup boa environment
boa.set_network_env(rpc_url)
boa.env.add_account(deployer)
boa.env.eoa = deployer.address

print(
    f"Chain: {boa.env.evm.patch.chain_id}, Deployer: {deployer.address}, Balance: {boa.env.get_balance(deployer.address)/1e18}"
)

# load contracts
math_path = "contracts/main/StableswapMath.vy"
views_path = "contracts/main/TwocryptoView.vy"
twocrypto_path = "contracts/main/Twocrypto.vy"

math_deployer = boa.load_partial(math_path)
views_deployer = boa.load_partial(views_path)

if DEPLOY:
    if boa.env.evm.patch.chain_id == 1:
        math_address = "0xBfDdF58Cb6ef84e115fF47c10e49A80B2653EA13"  # eth
        views_address = "0x1D788b7AB488bAF5E6c3609cF7f9C9b940C4C867"  # eth
    # elif boa.env.evm.patch.chain_id == 56:
    #     math_address = "0xd908A6ed4DCE4139f9b0F0E9c6c769539a9D7601"  # bsc
    #     views_address = "0x068712A87FFCB06cd1069Ad7526bDA8Bd564A910"  # bsc
    # elif boa.env.evm.patch.chain_id == 8453:
    #     math_address = "0x2Bd498ae431dC98694010950fcF8ACd3599f5512"
    #     views_address = "0xFcBA2D0133F705DD8bAf250a64f1DE0d7091F5Bd"  # base
    # elif boa.env.evm.patch.chain_id == 137:
    #     math_address = "0xe3AA3639BA550bED6ba5Fb9635bE89f9e35b9745"
    #     views_address = "0x5183A4dFC1adbfFDbf28293ce923fD4F844Cb216"  # polygon
    # elif boa.env.evm.patch.chain_id == 42793:
    #     math_address = "0xAE25375012a380D1a9B7C57021aCe72D83Cb5565"
    #     views_address = "0x2f39Fc9c39E99588dae8f822ce5886D395858FA7"  # etherlink
    # else:
    print("Deploying math contract...")
    math_contract = math_deployer.deploy()
    time.sleep(5)
    print("Deploying views contract...")
    views_contract = views_deployer.deploy()
    time.sleep(5)
    math_address = math_contract.address
    views_address = views_contract.address
    math_contract = math_deployer.at(math_address)
    views_contract = views_deployer.at(views_address)
    print("Deploying twocrypto contract...")
    twocrypto_deployer = twocrypto_with_periphery(
        twocrypto_path, views_contract.address, math_contract.address
    )
    twocrypto_contract = twocrypto_deployer.deploy_as_blueprint()
    time.sleep(5)
else:
    if boa.env.evm.patch.chain_id == 1:
        math_address = "0xBfDdF58Cb6ef84e115fF47c10e49A80B2653EA13"  # eth
        views_address = "0x1D788b7AB488bAF5E6c3609cF7f9C9b940C4C867"  # eth
        twocrypto_address = "0x94D8e42c786C090bC5378D205C5C531D6247BC3D"

    # elif boa.env.evm.patch.chain_id == 56:
    #     math_address = "0xd908A6ed4DCE4139f9b0F0E9c6c769539a9D7601"  # bsc
    #     views_address = "0x068712A87FFCB06cd1069Ad7526bDA8Bd564A910"  # bsc
    #     twocrypto_address = "0xbe365a090321E0E012f448B42feDfB74A7Ea4d9D"
    # elif boa.env.evm.patch.chain_id == 8453:
    #     math_address = "0x2Bd498ae431dC98694010950fcF8ACd3599f5512"
    #     views_address = "0xFcBA2D0133F705DD8bAf250a64f1DE0d7091F5Bd"  # base
    #     twocrypto_address = "0x56545b4640e5f0937e56843ad8f0a3cd44fc0785"
    # elif boa.env.evm.patch.chain_id == 137:
    #     math_address = "0xe3AA3639BA550bED6ba5Fb9635bE89f9e35b9745"
    #     views_address = "0x5183A4dFC1adbfFDbf28293ce923fD4F844Cb216"  # polygon
    #     twocrypto_address = "0xE6Ea1975544c1b4E56C900f600d7786D76Ea5944"
    # elif boa.env.evm.patch.chain_id == 42793:
    #     math_address = "0xAE25375012a380D1a9B7C57021aCe72D83Cb5565"
    #     views_address = "0x2f39Fc9c39E99588dae8f822ce5886D395858FA7"  # etherlink
    #     twocrypto_address = "0xC6644d4CEDd3700d4b977635e623bF531D59F39C"
    # else:
    #     raise ValueError(f"Chain ID {boa.env.evm.patch.chain_id} not supported")
    math_contract = math_deployer.at(math_address)
    views_contract = views_deployer.at(views_address)
    twocrypto_deployer = twocrypto_with_periphery(twocrypto_path, views_address, math_address)
    twocrypto_contract = twocrypto_deployer.at(twocrypto_address)

print(f"Math: {math_contract.address}")
print(f"Views: {views_contract.address}")
print(f"Twocrypto: {twocrypto_contract.address}")

# verify contracts on etherscan
etherscan_url = "https://api.etherscan.io/v2/api?chainid=" + str(boa.env.evm.patch.chain_id)
boa.set_etherscan(etherscan_url, etherscan_api_key)
verifier = Etherscan(etherscan_url, etherscan_api_key)

for contract in [math_contract, views_contract, twocrypto_contract]:
    contract.ctor_calldata = b""
    try:
        boa.verify(contract, verifier=verifier)
    except Exception as e:
        print(e)

# verify on blockscout (must change uri)
custom_verifier = Blockscout(uri="https://explorer.blockscout.com", api_key="")
for contract in [math_contract, views_contract, twocrypto_contract]:
    contract.ctor_calldata = b""
    try:
        boa.verify(contract, verifier=custom_verifier)
    except Exception as e:
        print(e)
# get factory
# factory = boa.from_etherscan("0x98EE851a00abeE0d95D08cF4CA2BdCE32aeaAF7F")
# print(factory.admin())

# set pool implementation
pool_id = int(keccak(text="fx50").hex(), 16)
print("Implementation ID:", pool_id)
# factory.set_pool_implementation(twocrypto_contract.address, pool_id, sender=deployer.address)
