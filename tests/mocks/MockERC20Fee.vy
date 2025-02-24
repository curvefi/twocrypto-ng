# pragma version ~=0.4.0

from snekmate.tokens import erc20
from snekmate.auth import ownable

from ethereum.ercs import IERC20

initializes: ownable
initializes: erc20[ownable := ownable]

exports: (erc20.approve, erc20.transferFrom)

MAX_FEE: constant(uint256) = 10_000
FEE_PERCENTAGE: public(immutable(uint256)) 

@deploy
def __init__(decimals: uint8, fee: uint256):
    ownable.__init__()
    erc20.__init__("mock", "mock", decimals, "mock", "mock")
    assert fee <= MAX_FEE, "fee must be less than or equal to 100%"
    FEE_PERCENTAGE = fee


@internal
def _transfer(owner: address, to: address, amount: uint256):
    # Adapted from snekmate to have fee on transfer

    assert owner != empty(address), "erc20: transfer from the zero address"
    assert to != empty(address), "erc20: transfer to the zero address"

    fee: uint256 = amount * FEE_PERCENTAGE // MAX_FEE
    amount -= fee

    erc20._burn(owner, fee)

    owner_balance: uint256 = erc20.balanceOf[owner]
    assert owner_balance >= amount, "erc20: transfer amount exceeds balance"
    # Deduct full amount from sender
    erc20.balanceOf[owner] = unsafe_sub(owner_balance, amount)
    # Credit recipient with full amount first
    erc20.balanceOf[to] = unsafe_add(erc20.balanceOf[to], amount)
    log IERC20.Transfer(owner, to, amount)


@external
def transfer(to: address, amount: uint256) -> bool:
    # Adapted from snekmate to have fee on transfer
    self._transfer(msg.sender, to, amount)
    return True