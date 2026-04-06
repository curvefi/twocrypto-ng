# pragma version 0.4.3
# pragma optimize gas
"""
@title TwocryptoPolicy
@notice External policy that defines fee surface and rebalance goal for twocrypto pools.
@dev The caller passes the transient `xp` and packed fee params so the hook can
     reproduce the legacy balance-based fee formula from `_fee` exactly.
"""
interface IPool:
    def A() -> uint256: view
    def price_scale() -> uint256: view
    def balances(i: uint256) -> uint256: view
    def D() -> uint256: view
    def totalSupply() -> uint256: view
    def precisions() -> uint256[N_COINS]: view
    def donation_shares() -> uint256: view
    def packed_fee_params() -> uint256: view
    def last_timestamp() -> uint256: view
    def last_prices() -> uint256: view

N_COINS: constant(uint256) = 2
PRECISION: constant(uint256) = 10**18
# POOL: public(immutable(IPool))
# FACTORY: public(immutable(address))
# Controller: public(address)

struct PoolState:
    xp: uint256[N_COINS]
    price_scale: uint256
    price_oracle: uint256
    last_prices: uint256
    virtual_price: uint256
    xcp_profit: uint256
    D: uint256
    ts: uint256

last_pool_state: public(PoolState)


# @deploy
# def __init__(pool_address: address, controller_address: address):
#     POOL = IPool(pool_address)
#     FACTORY = msg.sender
#     self.Controller = controller_address

@external
@view
def get_fee(xp: uint256[N_COINS], packed_fee_params: uint256) -> uint256:
    fee_params: uint256[3] = self._unpack_3(packed_fee_params)

    # warm up variable with sum of balances
    B: uint256 = xp[0] + xp[1]

    # balance indicator that goes from 10**18 (perfect pool balance)
    # to 0 (very imbalanced, 100:1 and worse)
    B = PRECISION * N_COINS**N_COINS * xp[0] // B * xp[1] // B

    # fee_gamma * balance_term / (fee_gamma * balance_term + 1 - balance_term)
    B = fee_params[2] * B // (fee_params[2] * B // PRECISION + PRECISION - B)

    # mid_fee * B + out_fee * (1 - B)
    return (fee_params[0] * B + fee_params[1] * (PRECISION - B)) // PRECISION

@external
@view
def get_price_scale() -> uint256:
    """
    @notice Returns the target price scale for the pool, which is used to determine direct the rebalance.
    @return uint256 The target price scale (1e18 for a 1:1 ratio)
    """
    return PRECISION


@external
def update_pool_state(xp: uint256[N_COINS],
                        price_scale: uint256,
                        price_oracle: uint256,
                        last_prices: uint256,
                        virtual_price: uint256,
                        xcp_profit: uint256,
                        D: uint256):
    # assert msg.sender == POOL.address, "auth!"
    self.last_pool_state = PoolState(
        xp = xp,
        price_scale = price_scale,
        price_oracle = price_oracle,
        last_prices = last_prices,
        virtual_price = virtual_price,
        xcp_profit = xcp_profit,
        D = D,
        ts = block.timestamp
    )


@internal
@pure
def _unpack_3(_packed: uint256) -> uint256[3]:
    return [
        (_packed >> 128) & 18446744073709551615,
        (_packed >> 64) & 18446744073709551615,
        _packed & 18446744073709551615,
    ]


@internal
@pure
def _unpack_2(packed: uint256) -> uint256[2]:
    return [packed & (2**128 - 1), packed >> 128]
