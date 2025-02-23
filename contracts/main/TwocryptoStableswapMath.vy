# pragma version ~=0.4.0
"""
@title TwocryptoMath
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2025 - all rights reserved
@notice Curve AMM Math for 2 unpegged assets (e.g. ETH <> USD).
    Unless otherwise agreed on, only contracts owned by Curve
    DAO or Swiss Stake GmbH are allowed to call this contract.
"""

from snekmate.utils import math

N_COINS: constant(uint256) = 2
A_MULTIPLIER: constant(uint256) = 10000

MIN_A: constant(uint256) = A_MULTIPLIER // 10
MAX_A: constant(uint256) = 100_000 * A_MULTIPLIER

version: public(constant(String[8])) = "???"


# ------------------------ AMM math functions --------------------------------


# newton_y is the same as get_y. Why separate method? Easy to make an internal method if needed


@external
@pure
def get_y(
    A: uint256,
    _gamma: uint256,
    xp: uint256[N_COINS],
    D: uint256,
    i: uint256
) -> uint256[2]:
    """
    Calculate x[i] if one reduces D from being calculated for xp to D

    Done by solving quadratic equation iteratively.
    x_1**2 + x_1 * (sum' - (A*n**n - 1) * D / (A * n**n)) = D ** (n + 1) / (n ** (2 * n) * prod' * A)
    x_1**2 + b*x_1 = c

    x_1 = (x_1**2 + c) / (2*x_1 + b)
    """
    # x in the input is converted to the same price/precision

    assert i < N_COINS  # dev: i above N_COINS

    S_: uint256 = 0
    _x: uint256 = 0
    y_prev: uint256 = 0
    c: uint256 = D
    Ann: uint256 = A * N_COINS

    for _i: uint256 in range(N_COINS):
        if _i != i:
            _x = xp[_i]
        else:
            continue
        S_ += _x
        c = c * D // (_x * N_COINS)

    c = c * D * A_MULTIPLIER // (Ann * N_COINS)
    b: uint256 = S_ + D * A_MULTIPLIER // Ann
    y: uint256 = D

    for _i: uint256 in range(255):
        y_prev = y
        y = (y*y + c) // (2 * y + b - D)
        # Equality with the precision of 1
        if y > y_prev:
            if y - y_prev <= 1:
                return [y, 0]
        else:
            if y_prev - y <= 1:
                return [y, 0]
    raise


@external
@view
def newton_D(_amp: uint256, gamma: uint256, _xp: uint256[N_COINS], K0_prev: uint256 = 0) -> uint256:
    """
    Finding the invariant using Newton method.
    D invariant calculation in non-overflowing integer operations
    iteratively

    A * sum(x_i) * n**n + D = A * D * n**n + D**(n+1) // (n**n * prod(x_i))

    Converging solution:
    D[j+1] = (A * n**n * sum(x_i) - D[j]**(n+1) // (n**n prod(x_i))) // (A * n**n - 1)
    """
    # gamma and K0_prev are ignored
    # _amp is already multiplied by a [higher] A_MULTIPLIER

    S: uint256 = 0
    for x: uint256 in _xp:
        S += x
    if S == 0:
        return 0

    D: uint256 = S
    Ann: uint256 = _amp * N_COINS

    for i: uint256 in range(255):

        D_P: uint256 = D
        for x: uint256 in _xp:
            D_P = D_P * D // x
        D_P //= pow_mod256(N_COINS, N_COINS)
        Dprev: uint256 = D

        # (Ann * S / A_PRECISION + D_P * N_COINS) * D / ((Ann - A_PRECISION) * D / A_PRECISION + (N_COINS + 1) * D_P)
        D = (
            (unsafe_div(Ann * S, A_MULTIPLIER) + D_P * N_COINS) * D
            //
            (
                unsafe_div((Ann - A_MULTIPLIER) * D, A_MULTIPLIER) +
                unsafe_add(N_COINS, 1) * D_P
            )
        )

        # Equality with the precision of 1
        if D > Dprev:
            if D - Dprev <= 1:
                return D
        else:
            if Dprev - D <= 1:
                return D
    # convergence typically occurs in 4 rounds or less, this should be unreachable!
    # if it does happen the pool is borked and LPs can withdraw via `remove_liquidity`
    raise "didn't converge"


@external
@pure
def get_p(
    xp: uint256[N_COINS],
    D: uint256,
    Agamma: uint256[2]
) -> uint256:

    # dx_0 / dx_1 only, however can have any number of coins in pool
    ANN: uint256 = unsafe_mul(Agamma[0], N_COINS)
    Dr: uint256 = unsafe_div(D, pow_mod256(N_COINS, N_COINS))

    for i: uint256 in range(N_COINS):
        Dr = Dr * D // xp[i]

    xp0_A: uint256 = unsafe_div(ANN * xp[0], A_MULTIPLIER)

    return 10**18 * (xp0_A + unsafe_div(Dr * xp[0], xp[1])) // (xp0_A + Dr)
