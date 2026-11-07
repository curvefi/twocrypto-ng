import boa
from eth_utils import to_checksum_address


def mint_for_testing(token_contract, addr, amount, mint_eth=False):

    addr = to_checksum_address(addr)

    if token_contract.symbol() == "WETH":
        boa.env.set_balance(addr, boa.env.get_balance(addr) + amount)
        if not mint_eth:
            with boa.env.prank(addr):
                token_contract.deposit(value=amount)
    else:
        token_contract.eval(f"self.totalSupply += {amount}")
        token_contract.eval(f"self.balanceOf[{addr}] += {amount}")
        # Transfer field names differ between tokens (mock vs pool LP token).
        sender, receiver, value = [
            field["name"]
            for event in token_contract.abi
            if event.get("type") == "event" and event["name"] == "Transfer"
            for field in event["inputs"]
        ]
        token_contract.eval(
            f"log Transfer({sender}=empty(address), {receiver}={addr}, {value}={amount})"
        )
