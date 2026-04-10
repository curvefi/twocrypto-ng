# pragma version 0.4.3
# pragma optimize gas
"""
@title TwocryptoPolicy
@notice External policy that defines fee surface and rebalance goal for twocrypto pools.
@dev The caller passes the transient `xp` and packed fee params so the hook can
     reproduce the legacy balance-based fee formula from `_fee` exactly.
"""
from snekmate.utils import math

interface IPool:
    def price_scale() -> uint256: view
    def price_oracle() -> uint256: view
    def last_prices() -> uint256: view
    def virtual_price() -> uint256: view
    def xcp_profit() -> uint256: view
    def D() -> uint256: view
    def balances(i: uint256) -> uint256: view

N_COINS: constant(uint256) = 2
PRECISION: constant(uint256) = 10**18
POOL: public(immutable(address))

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


@deploy
def __init__(pool: address):
    POOL = pool


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
def get_price_scale(packed_rebalancing_params: uint256) -> uint256:
    state: PoolState = self.last_pool_state
    if state.ts == 0:
        return 0

    price_scale: uint256 = state.price_scale
    price_oracle: uint256 = state.price_oracle
    rebalancing_params: uint256[3] = self._unpack_3(packed_rebalancing_params)

    if state.ts < block.timestamp and price_scale > 0:
        alpha: uint256 = self._wad_exp(
            -convert(
                unsafe_div((block.timestamp - state.ts) * PRECISION, rebalancing_params[2]),
                int256,
            )
        )
        ema_input: uint256 = min(
            max(state.last_prices, price_scale // 2),
            2 * price_scale,
        )
        price_oracle = unsafe_div(
            ema_input * (PRECISION - alpha) + price_oracle * alpha,
            PRECISION,
        )

    norm: uint256 = unsafe_div(price_oracle * PRECISION, price_scale)
    if norm > PRECISION:
        norm = unsafe_sub(norm, PRECISION)
    else:
        norm = unsafe_sub(PRECISION, norm)

    adjustment_step: uint256 = min(
        unsafe_div(norm, 5),
        rebalancing_params[1],
    )
    if adjustment_step <= rebalancing_params[0]:
        return price_scale

    return unsafe_div(
        price_scale * unsafe_sub(norm, adjustment_step) +
        adjustment_step * price_oracle,
        norm,
    )


@external
def update_pool_state(xp: uint256[N_COINS],
                        price_scale: uint256,
                        price_oracle: uint256,
                        last_prices: uint256,
                        virtual_price: uint256,
                        xcp_profit: uint256,
                        D: uint256):
    assert msg.sender == POOL, "auth!"
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
def _wad_exp(x: int256) -> uint256:
    return convert(math._wad_exp(x), uint256)


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
