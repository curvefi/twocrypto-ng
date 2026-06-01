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
ANKR_API_KEY = os.environ.get("ANKR_API_KEY")
# rpc_url = "https://bsc-dataseed.bnbchain.org"
# rpc_url = f"https://lb.drpc.org/ogrpc?network=eth&dkey={DRPC_API_KEY}"
rpc_url = f"https://rpc.ankr.com/gnosis/{ANKR_API_KEY}"
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
    elif boa.env.evm.patch.chain_id == 56:
        math_address = "0xB9EA065629A44A73f9E7e9f99bf962992A560eb8"  # bsc
        views_address = "0xF2E81011C13bA558076b8fd5247913e98C1cFf06"  # bsc
    elif boa.env.evm.patch.chain_id == 8453:
        math_address = "0x6eE54BABC0573879d821b0964ea794BF0DBb25e8"
        views_address = "0xC6A535CE48049C219Bc62dd739219108a51294C6"  # base
    elif boa.env.evm.patch.chain_id == 137:
        math_address = "0x59f1C56176E98d506Bb400578DFFc63CbbA2c072"
        views_address = "0x832732f5aFA15DbD74541Aa093a98B2aA36eEa69"  # polygon
    elif boa.env.evm.patch.chain_id == 100:
        math_address = "0x206871A7C8F01Ea4DFe6c632131B5330cF629C21"  # gnosis
        views_address = "0x7Da608576681c7ad4D3aC1B5F913E7b66018fe15"  # gnosis
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
    elif boa.env.evm.patch.chain_id == 56:
        math_address = "0xB9EA065629A44A73f9E7e9f99bf962992A560eb8"  # bsc
        views_address = "0xF2E81011C13bA558076b8fd5247913e98C1cFf06"  # bsc
        twocrypto_address = "0x85C44766d26616E581aa090f1Dc69abAc46A84D6"
    elif boa.env.evm.patch.chain_id == 8453:
        math_address = "0x6eE54BABC0573879d821b0964ea794BF0DBb25e8"
        views_address = "0xC6A535CE48049C219Bc62dd739219108a51294C6"  # base
        twocrypto_address = "0x5B7dA0f56dD31df86eD34FC0b02d6BC62d4E3925"
    elif boa.env.evm.patch.chain_id == 137:
        math_address = "0x59f1C56176E98d506Bb400578DFFc63CbbA2c072"
        views_address = "0x832732f5aFA15DbD74541Aa093a98B2aA36eEa69"  # polygon
        twocrypto_address = "0xf823F26E359fBE1d3cB0ff1534B24846aC02A0Bb"
    elif boa.env.evm.patch.chain_id == 100:
        math_address = "0x206871A7C8F01Ea4DFe6c632131B5330cF629C21"
        views_address = "0x7Da608576681c7ad4D3aC1B5F913E7b66018fe15"  # gnosis
        twocrypto_address = "0x81147a0b418fB870259feD359d0956ce85C16286"
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
