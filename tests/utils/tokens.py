import boa
from eth_utils.address import to_checksum_address


def mint_for_testing(token_contract, addr, amount, mint_eth=False):
    addr = to_checksum_address(addr)

    if token_contract.symbol() == "WETH":
        boa.env.set_balance(addr, boa.env.get_balance(addr) + amount)
        if not mint_eth:
            with boa.env.prank(addr):
                token_contract.deposit(value=amount)
    else:
        with boa.env.prank(addr):
            token_contract._mint_for_testing(addr, amount)
