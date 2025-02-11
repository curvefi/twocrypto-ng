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

A_PRECISION: constant(uint256) = 100

VERSION: public(constant(String[8])) = "???"

@external
@pure
def wad_exp(x: int256) -> int256:
    return math._wad_exp(x)

# TODO remove j as it can be inferred from i with N_COINS=2
@external
@view
def get_y(
    i: uint256,
    j: uint256,
    x: uint256, # xp[i] + dx
    xp: uint256[N_COINS], # [xp[0], xp[1]]
    _amp: uint256,
    _D: uint256
) -> uint256:
    """
    Calculate x[j] if one makes x[i] = x

    Done by solving quadratic equation iteratively.
    x_1**2 + x_1 * (sum' - (A*n**n - 1) * D // (A * n**n)) = D ** (n + 1) // (n ** (2 * n) * prod' * A)
    x_1**2 + b*x_1 = c

    x_1 = (x_1**2 + c) // (2*x_1 + b)
    """
    # x in the input is converted to the same price/precision

    assert i != j       # dev: same coin
    assert j >= 0       # dev: j below zero
    assert j < N_COINS # dev: j above N_COINS

    # should be unreachable, but good for safety
    assert i >= 0
    assert i < N_COINS

    amp: uint256 = _amp
    D: uint256 = _D

    S_: uint256 = 0
    _x: uint256 = 0
    y_prev: uint256 = 0
    c: uint256 = D
    Ann: uint256 = amp * N_COINS

    for _i: uint256 in range(N_COINS):

        if _i == N_COINS:
            break

        if _i == i:
            _x = x
        elif _i != j:
            _x = xp[_i]
        else:
            continue

        S_ += _x
        c = c * D // (_x * N_COINS)

    c = c * D * A_PRECISION // (Ann * N_COINS)
    b: uint256 = S_ + D * A_PRECISION // Ann  # - D
    y: uint256 = D

    for _i: uint256 in range(255):
        y_prev = y
        y = (y*y + c) // (2 * y + b - D)
        # Equality with the precision of 1
        if y > y_prev:
            if y - y_prev <= 1:
                return y
        else:
            if y_prev - y <= 1:
                return y
    raise

@pure
@internal
def get_D(
    _xp: uint256[N_COINS],
    _amp: uint256
) -> uint256:
    """
    D invariant calculation in non-overflowing integer operations
    iteratively

    A * sum(x_i) * n**n + D = A * D * n**n + D**(n+1) // (n**n * prod(x_i))

    Converging solution:
    D[j+1] = (A * n**n * sum(x_i) - D[j]**(n+1) // (n**n prod(x_i))) // (A * n**n - 1)
    """
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
            (unsafe_div(Ann * S, A_PRECISION) + D_P * N_COINS) * D
            //
            (
                unsafe_div((Ann - A_PRECISION) * D, A_PRECISION) +
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
    raise

@external
@pure
def get_p(
    xp: uint256[N_COINS],
    amp: uint256,
    D: uint256,
) -> uint256[N_COINS]:

    # dx_0 / dx_1 only, however can have any number of coins in pool
    ANN: uint256 = unsafe_mul(amp, N_COINS)
    Dr: uint256 = unsafe_div(D, pow_mod256(N_COINS, N_COINS))

    for i: uint256 in range(N_COINS):
        Dr = Dr * D // xp[i]

    p: DynArray[uint256, N_COINS] = empty(DynArray[uint256, N_COINS])
    xp0_A: uint256 = unsafe_div(ANN * xp[0], A_PRECISION)

    for i: uint256 in range(1, N_COINS):

        if i == N_COINS:
            break

        p.append(10**18 * (xp0_A + unsafe_div(Dr * xp[0], xp[i])) // (xp0_A + Dr))

    # TODO naive implementaion, should build uint256 directly
    p_: uint256[N_COINS] = [p[0], p[1]]
    return p_
