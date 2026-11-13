# pragma version 0.4.3

"""
@title Policy Math
@notice The arithmetic YBOraclizedPolicy uses but does not decide, in three
        sections:
            STABLESWAP MATH   get_p, the pool math's marginal price
            POOL QUOTE        the pool's balances as it scales them, and its
                              swap and fee for get_dy_with_report
            EMA               an exponential moving average with a true
                              half-life
@dev Initialized with the pool for the quote section; the other two are pure.
     Pools with StableswapMath only. Prices have 18 decimals, fees are in
     FEE_PRECISION (1e10 = 100%).
@license Copyright (c) Curve.Fi, 2020 - 2026 - all rights reserved
@author curve.fi
"""

from snekmate.utils import math as snekmate_math

N_COINS: constant(uint256) = 2
PRECISION: constant(uint256) = 10**18

################################################################
#                        STABLESWAP MATH                       #
################################################################

# StableswapMath exposes get_p only as an external function. _get_p is copied
# line by line from contracts/main/StableswapMath.vy, which stays byte-identical
# to the deployed math.

A_MULTIPLIER: constant(uint256) = 10000


@internal
@pure
def _get_p(
    _xp: uint256[N_COINS], _D: uint256, _A_gamma: uint256[N_COINS]
) -> uint256:
    """
    @notice Calculates dx/dy.
    @dev Output needs to be multiplied with price_scale to get the actual value.
    @param _xp Balances of the pool.
    @param _D Current value of D.
    @param _A_gamma Amplification coefficient and gamma.
    """
    # dx_0 / dx_1 only, however can have any number of coins in pool
    ANN: uint256 = unsafe_mul(_A_gamma[0], N_COINS)
    Dr: uint256 = unsafe_div(_D, N_COINS**N_COINS)

    for i: uint256 in range(N_COINS):
        Dr = Dr * _D // _xp[i]

    xp0_A: uint256 = unsafe_div(ANN * _xp[0], A_MULTIPLIER)

    return 10**18 * (xp0_A + unsafe_div(Dr * _xp[0], _xp[1])) // (xp0_A + Dr)

################################################################
#                          POOL QUOTE                          #
################################################################

# _get_dy_nofee is TwocryptoView._get_dy_nofee with the pool's state read
# directly and the pool's math and coin1 precision held as immutables. It
# returns the D it solved as well: during an A ramp the pool re-solves D before
# asking the policy for the fee, and a quote must hand the fee that same D. The
# policy prices the fee, and _apply_fee applies it as the pool does.

FEE_PRECISION: constant(uint256) = 10**10


interface Pool:
    def A() -> uint256: view
    def D() -> uint256: view
    def balances(i: uint256) -> uint256: view
    def price_scale() -> uint256: view
    def precisions() -> uint256[N_COINS]: view
    def POLICY() -> address: view
    def MATH() -> Math: view
    def future_A_gamma_time() -> uint256: view
    def last_timestamp() -> uint256: view
    def fee_calc(xp: uint256[N_COINS]) -> uint256: view


interface Math:
    def get_y(
        ANN: uint256, gamma: uint256, x: uint256[N_COINS], D: uint256, i: uint256
    ) -> uint256[2]: view
    def newton_D(
        ANN: uint256, gamma: uint256, x_unsorted: uint256[N_COINS], K0_prev: uint256
    ) -> uint256: view


POOL: immutable(address)
MATH: immutable(Math)  # the pool's math, immutable in the pool
PRECISION1: immutable(uint256)  # the pool's coin1 precision; coin0's is 1


@deploy
def __init__(pool: address):
    """@param pool Twocrypto pool whose coin0 has precision 1"""
    POOL = pool
    MATH = staticcall Pool(pool).MATH()
    PRECISION1 = (staticcall Pool(pool).precisions())[1]


@internal
@view
def _xp(price_scale: uint256) -> uint256[N_COINS]:
    """@dev The pool's balances as Twocrypto._xp scales them at price_scale."""
    return [
        staticcall Pool(POOL).balances(0),
        staticcall Pool(POOL).balances(1) * PRECISION1 * price_scale // PRECISION,
    ]


@internal
@view
def _get_dy_nofee(i: uint256, j: uint256, dx: uint256) -> (uint256, uint256[N_COINS], uint256):
    """
    @return (dy before the fee in coin j, the pool's balances after the swap and
            before its fee with coin1 scaled by price_scale, the D the swap used)
    """
    assert i != j and i < N_COINS and j < N_COINS, "coin index out of range"
    # A detached policy no longer prices the pool's swaps
    assert staticcall Pool(POOL).POLICY() == self, "not attached"

    xp: uint256[N_COINS] = [staticcall Pool(POOL).balances(0), staticcall Pool(POOL).balances(1)]
    price_scale: uint256 = staticcall Pool(POOL).price_scale()
    A: uint256 = staticcall Pool(POOL).A()

    # StableswapMath ignores gamma: 0 here
    D: uint256 = staticcall Pool(POOL).D()
    if staticcall Pool(POOL).future_A_gamma_time() > staticcall Pool(POOL).last_timestamp():
        ramp_xp: uint256[N_COINS] = [xp[0], xp[1] * price_scale * PRECISION1 // PRECISION]
        D = staticcall MATH.newton_D(A, 0, ramp_xp, 0)

    xp[i] += dx
    xp = [xp[0], xp[1] * price_scale * PRECISION1 // PRECISION]

    y_out: uint256[2] = staticcall MATH.get_y(A, 0, xp, D, j)
    assert y_out[0] < xp[j], "unsafe value for y"
    dy: uint256 = xp[j] - y_out[0] - 1
    xp[j] = y_out[0]
    if j > 0:
        dy = dy * PRECISION // price_scale // PRECISION1

    return dy, xp, D


@internal
@view
def _apply_fee(dy: uint256, xp: uint256[N_COINS], fee: uint256) -> uint256:
    """
    @dev dy less a policy fee, or less the pool's native fee at xp for 0, as
         Twocrypto._fee applies them. The policy's fees are within the pool's
         clamp to [MIN_FEE, 100%]: at least base_fee >= MIN_FEE, at most 10%.
    """
    pool_fee: uint256 = fee
    if fee == 0:
        pool_fee = staticcall Pool(POOL).fee_calc(xp)
    return dy - pool_fee * dy // FEE_PRECISION

################################################################
#                              EMA                             #
################################################################

LN2: constant(uint256) = 693_147_180_559_945_309


@internal
@pure
def _ema(ema: uint256, price: uint256, dt: uint256, half_life: uint256) -> uint256:
    """@dev ema moved toward price over dt seconds; half_life is in seconds."""
    # alpha = exp(-ln(2) * dt / half_life): the parameter is a true half-life
    alpha: uint256 = convert(
        snekmate_math._wad_exp(-convert(dt * LN2 // half_life, int256)), uint256
    )
    return (price * (PRECISION - alpha) + ema * alpha) // PRECISION
