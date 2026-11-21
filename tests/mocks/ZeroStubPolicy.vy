# pragma version 0.4.3
# pragma optimize gas

N_COINS: constant(uint256) = 2


@external
@view
def get_fee(xp: uint256[N_COINS]) -> uint256:
    return 0


@external
@view
def get_price_scale() -> uint256:
    return 0


@external
def update_pool_state(
    xp: uint256[N_COINS],
    price_scale: uint256,
    price_oracle: uint256,
    last_prices: uint256,
    virtual_price: uint256,
    xcp_profit: uint256,
    D: uint256,
    oracle_timestamp: uint256,
):
    pass
