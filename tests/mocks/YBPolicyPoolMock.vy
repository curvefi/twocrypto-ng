# pragma version 0.4.3
# pragma optimize gas

interface Policy:
    def update_pool_state(
        xp: uint256[2],
        price_scale: uint256,
        price_oracle: uint256,
        last_prices: uint256,
        virtual_price: uint256,
        xcp_profit: uint256,
        D: uint256,
        oracle_timestamp: uint256,
    ): nonpayable

PRECISION: constant(uint256) = 10**18

price_scale: public(uint256)
price_oracle: public(uint256)
last_prices: public(uint256)


@deploy
def __init__(initial_price: uint256, initial_oracle: uint256):
    self.price_scale = initial_price
    self.price_oracle = initial_oracle
    self.last_prices = initial_price


@external
def update_policy(
    policy: address,
    price_scale: uint256,
    price_oracle: uint256,
    last_prices: uint256,
):
    self.price_scale = price_scale
    self.price_oracle = price_oracle
    self.last_prices = last_prices
    extcall Policy(policy).update_pool_state(
        [PRECISION, PRECISION],
        price_scale,
        price_oracle,
        last_prices,
        PRECISION,
        PRECISION,
        2 * PRECISION,
        block.timestamp,
    )
