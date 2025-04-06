# pragma version 0.4.1


from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed

implements: IERC20
implements: IERC20Detailed

# We initialize the ownable module here because
# it used by snekamate. However we won't use it.
from snekmate.auth import ownable
initializes: ownable

from snekmate.tokens import erc20
initializes: erc20[ownable := ownable]
# We intentionally do not expose `IERC20Detailed`
# functionalities from here to override them.
exports: (
    erc20.transfer,
    erc20.transferFrom,
    erc20.approve,
    erc20.balanceOf,
    erc20.allowance,
    erc20.totalSupply,
)

# If you are still not hardcoding decimals to 18, you should.
DECIMALS: constant(uint8) = 18

# We override name and symbol to have more chars since snakemate's
# implementation is highly restrictive for security reasons.
symbol: public(String[32])
name: public(String[64])

@deploy
def __init__(name: String[64], symbol: String[32]):
    # This approach burns a bit of gas at construction since we don't
    # actually use the ownable module.
    ownable.__init__()

    # This approach burns a bit of gas at construction since we don't
    # actually use name, symbol, decimals, nor name_eip712, version_eip712
    # (required for permit).
    erc20.__init__("", "", DECIMALS, "", "")

    # Instead we rely on our own memory slots for symbol and name.
    self.name = name
    self.symbol = symbol

@view
@external
def decimals() -> uint8:
    return DECIMALS
