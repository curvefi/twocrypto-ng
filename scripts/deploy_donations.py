import boa
import os
from eth_account import Account
from boa.explorer import Etherscan
from secure_key_utils import decrypt_private_key, getpass
import time
from eth_utils import keccak

# deploy as blueprints
DEPLOY = False
ADMIN_FEE = 10**10 * 50 // 100


def twocrypto_with_periphery(twocrypto_path, views_address, math_address, admin_fee):
    with open(twocrypto_path, "r") as f:
        twocrypto_code = f.read()
    twocrypto_code = twocrypto_code.replace(
        "self.MATH = Math(empty(address))", f"self.MATH = Math({math_address})", 1
    )
    twocrypto_code = twocrypto_code.replace(
        "self.VIEW = Views(empty(address))", f"self.VIEW = Views({views_address})", 1
    )
    twocrypto_code = twocrypto_code.replace(
        "self.admin_fee = 10**10 * 50 // 100", f"self.admin_fee = {admin_fee}", 1
    )
    assert f"self.MATH = Math({math_address})" in twocrypto_code
    assert f"self.VIEW = Views({views_address})" in twocrypto_code
    assert f"self.admin_fee = {admin_fee}" in twocrypto_code
    return boa.loads_partial(twocrypto_code)


# rpc_url = "https://bsc-dataseed.bnbchain.org"
# rpc_url = "https://eth.drpc.org"
rpc_url = "https://mainnet.base.org"
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
        math_address = "0x79839c2D74531A8222C0F555865aAc1834e82e51"  # eth
        views_address = "0x35048188c02cbc9239e1e5ecb3761eF9dfDcD31f"  # eth
    elif boa.env.evm.patch.chain_id == 56:
        math_address = "0xd908A6ed4DCE4139f9b0F0E9c6c769539a9D7601"  # bsc
        views_address = "0x068712A87FFCB06cd1069Ad7526bDA8Bd564A910"  # bsc
    elif boa.env.evm.patch.chain_id == 8453:
        math_address = "0x2Bd498ae431dC98694010950fcF8ACd3599f5512"
        views_address = "0xFcBA2D0133F705DD8bAf250a64f1DE0d7091F5Bd"  # base
    else:
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
        twocrypto_path, views_contract.address, math_contract.address, ADMIN_FEE
    )
    twocrypto_contract = twocrypto_deployer.deploy_as_blueprint()
    time.sleep(5)
else:
    if boa.env.evm.patch.chain_id == 1:
        math_address = "0x79839c2D74531A8222C0F555865aAc1834e82e51"  # eth
        views_address = "0x35048188c02cbc9239e1e5ecb3761eF9dfDcD31f"  # eth
        twocrypto_address = "0xD1FAeCA80d6FDd1DF4CBcCe4b2551b6Ee63Ae3D6"

    elif boa.env.evm.patch.chain_id == 56:
        math_address = "0xd908A6ed4DCE4139f9b0F0E9c6c769539a9D7601"  # bsc
        views_address = "0x068712A87FFCB06cd1069Ad7526bDA8Bd564A910"  # bsc
        twocrypto_address = "0xbe365a090321E0E012f448B42feDfB74A7Ea4d9D"
    elif boa.env.evm.patch.chain_id == 8453:
        math_address = "0x2Bd498ae431dC98694010950fcF8ACd3599f5512"
        views_address = "0xFcBA2D0133F705DD8bAf250a64f1DE0d7091F5Bd"  # base
        twocrypto_address = "0x56545b4640e5f0937e56843ad8f0a3cd44fc0785"
    else:
        raise ValueError(f"Chain ID {boa.env.evm.patch.chain_id} not supported")
    math_contract = math_deployer.at(math_address)
    views_contract = views_deployer.at(views_address)
    twocrypto_deployer = twocrypto_with_periphery(
        twocrypto_path, views_address, math_address, ADMIN_FEE
    )
    twocrypto_contract = twocrypto_deployer.at(twocrypto_address)

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
# factory = boa.from_etherscan("0x98EE851a00abeE0d95D08cF4CA2BdCE32aeaAF7F")
# print(factory.admin())

# set pool implementation
pool_id = int(keccak(text="fx50").hex(), 16)
print("Implementation ID:", pool_id)
# factory.set_pool_implementation(twocrypto_contract.address, pool_id, sender=deployer.address)
