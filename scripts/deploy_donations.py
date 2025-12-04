import boa
import os
from eth_account import Account
from boa.explorer import Etherscan
from secure_key_utils import decrypt_private_key, getpass

# deploy as blueprints
DEPLOY = True
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


rpc_url = "https://polygon.drpc.org"
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
    math_contract = math_deployer.deploy()
    views_contract = views_deployer.deploy()
    math_address = math_contract.address
    views_address = views_contract.address
    # math_address = "0x79839c2D74531A8222C0F555865aAc1834e82e51"
    # views_address = "0x35048188c02cbc9239e1e5ecb3761eF9dfDcD31f"

    math_contract = math_deployer.at(math_address)
    views_contract = views_deployer.at(views_address)

    twocrypto_deployer = twocrypto_with_periphery(
        twocrypto_path, views_contract.address, math_contract.address, ADMIN_FEE
    )
    twocrypto_contract = twocrypto_deployer.deploy_as_blueprint()
else:
    math_address = "0x79839c2D74531A8222C0F555865aAc1834e82e51"
    views_address = "0x35048188c02cbc9239e1e5ecb3761eF9dfDcD31f"
    twocrypto_address = "0x7D3ba8D1143e5f6CeE71C659375DcB95B3302D62"

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
# pool_id = int(keccak(text="fx").hex(), 16)
# print("Implementation ID:", pool_id)
# factory.set_pool_implementation(twocrypto_contract.address, pool_id, sender=deployer.address)

# set pool periphery
# pool = boa.from_etherscan("0xC69A9c962A65a5E11D38A0f23050D5Ac319d18DD")
# pool.set_periphery(views_contract.address, math_contract.address, sender=deployer.address)
# pool.set_admin_fee(2500000000, sender=deployer.address)
