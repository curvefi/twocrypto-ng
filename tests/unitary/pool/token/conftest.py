from copy import deepcopy

import boa
import pytest

# from eth_account import Account as EthAccount
# from eth_account._utils.encode_typed_data.encoding_and_hashing import (
#     hash_message,
#     hash_domain,
# )
# from eth_account.messages import SignableMessage
from hexbytes import HexBytes


@pytest.fixture(scope="module")
def sign_permit():
    def _sign_permit(swap, owner, spender, value, deadline):
        raise Exception(
            "hash_message is not available in the new version of eth-account"
        )

        PERMIT_STRUCT = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                    {"name": "salt", "type": "bytes32"},
                ],
                "Permit": [
                    {"name": "owner", "type": "address"},
                    {"name": "spender", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "deadline", "type": "uint256"},
                ],
            },
            "primaryType": "Permit",
        }

        struct = deepcopy(PERMIT_STRUCT)
        struct["domain"] = dict(
            name=swap.name(),
            version=swap.version(),
            chainId=boa.env.evm.patch.chain_id,
            verifyingContract=swap.address,
            salt=HexBytes(swap.salt()),
        )
        struct["message"] = dict(
            owner=owner.address,
            spender=spender,
            value=value,
            nonce=swap.nonces(owner.address),
            deadline=deadline,
        )
        # TODO - hash_message is not available in the new version of
        #  eth-account
        # this needs to be fixed
        # signable_message = SignableMessage(
        #     b"\x01", hash_domain(struct), hash_message(struct)
        # )
        # return EthAccount.sign_message(signable_message, owner._private_key)

    return _sign_permit
