import boa


def mint_for_testing(token_contract, addr, amount, mint_eth=False):
    # TODO remove this function completely
    boa.deal(token_contract, addr, amount)
    # addr = to_checksum_address(addr)

    # if token_contract.symbol() == "WETH":
    #     boa.env.set_balance(addr, boa.env.get_balance(addr) + amount)
    #     if not mint_eth:
    #         with boa.env.prank(addr):
    #             token_contract.deposit(value=amount)
    # else:
    #     token_contract.eval(f"self.totalSupply += {amount}")
    #     token_contract.eval(f"self.balanceOf[{addr}] += {amount}")
    #     token_contract.eval(f"log Transfer(empty(address), {addr}, {amount})")
