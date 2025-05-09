# pragma version 0.4.1
"""
@title TwocryptoView
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2025 - all rights reserved
@notice This contract contains view-only external methods which can be
        gas-inefficient when called from smart contracts.
"""

from ethereum.ercs import IERC20

from interfaces import ITwocrypto
from interfaces import ITwocryptoMath
from interfaces import ITwocryptoView

import constants as c
# Trick until the compiler supports `from constants import N_COINS`
N_COINS: constant(uint256) = c.N_COINS
WAD: constant(uint256) = c.WAD

@external
@view
def get_dy(
    i: uint256, j: uint256, dx: uint256, swap: address
) -> uint256:

    dy: uint256 = 0
    xp: uint256[N_COINS] = empty(uint256[N_COINS])

    # dy = (get_y(x + dx) - y) * (1 - fee)
    dy, xp = self._get_dy_nofee(i, j, dx, swap)
    dy -= staticcall ITwocrypto(swap).fee_calc(xp) * dy // 10**10

    return dy


@view
@external
def get_dx(
    i: uint256, j: uint256, dy: uint256, swap: address
) -> uint256:

    dx: uint256 = 0
    xp: uint256[N_COINS] = empty(uint256[N_COINS])
    fee_dy: uint256 = 0
    _dy: uint256 = dy

    # for more precise dx (but never exact), increase num loops
    for k: uint256 in range(5):
        dx, xp = self._get_dx_fee(i, j, _dy, swap)
        fee_dy = staticcall ITwocrypto(swap).fee_calc(xp) * _dy // 10**10
        _dy = dy + fee_dy + 1

    return dx


@view
@external
def calc_withdraw_one_coin(
    token_amount: uint256, i: uint256, swap: address
) -> uint256:

    return self._calc_withdraw_one_coin(token_amount, i, swap)[0]


@view
@external
def calc_token_amount(
    amounts: uint256[N_COINS], deposit: bool, swap: address
) -> uint256:

    d_token: uint256 = 0
    amountsp: uint256[N_COINS] = empty(uint256[N_COINS])
    xp: uint256[N_COINS] = empty(uint256[N_COINS])

    d_token, amountsp, xp = self._calc_dtoken_nofee(amounts, deposit, swap)
    d_token -= (
        staticcall ITwocrypto(swap).calc_token_fee(amountsp, xp) * d_token // 10**10 + 1
    )

    return d_token


@external
@view
def calc_fee_get_dy(i: uint256, j: uint256, dx: uint256, swap: address
) -> uint256:

    dy: uint256 = 0
    xp: uint256[N_COINS] = empty(uint256[N_COINS])
    dy, xp = self._get_dy_nofee(i, j, dx, swap)

    return (staticcall ITwocrypto(swap).fee_calc(xp)) * dy // 10**10


@external
@view
def calc_fee_withdraw_one_coin(
    token_amount: uint256, i: uint256, swap: address
) -> uint256:

    return self._calc_withdraw_one_coin(token_amount, i, swap)[1]


@view
@external
def calc_fee_token_amount(
    amounts: uint256[N_COINS], deposit: bool, swap: address
) -> uint256:

    d_token: uint256 = 0
    amountsp: uint256[N_COINS] = empty(uint256[N_COINS])
    xp: uint256[N_COINS] = empty(uint256[N_COINS])
    d_token, amountsp, xp = self._calc_dtoken_nofee(amounts, deposit, swap)

    return (staticcall ITwocrypto(swap).calc_token_fee(amountsp, xp)) * d_token // 10**10 + 1


@internal
@view
def _calc_D_ramp(
    A: uint256,
    gamma: uint256,
    xp: uint256[N_COINS],
    precisions: uint256[N_COINS],
    price_scale: uint256,
    swap: address
) -> uint256:

    math: ITwocryptoMath = staticcall ITwocrypto(swap).MATH()
    D: uint256 = staticcall ITwocrypto(swap).D()
    if staticcall ITwocrypto(swap).future_A_gamma_time() > block.timestamp:
        _xp: uint256[N_COINS] = xp
        _xp[0] *= precisions[0]
        _xp[1] = _xp[1] * price_scale * precisions[1] // WAD
        D = staticcall math.newton_D(A, gamma, _xp, 0)

    return D


@internal
@view
def _get_dx_fee(
    i: uint256, j: uint256, dy: uint256, swap: address
) -> (uint256, uint256[N_COINS]):

    # here, dy must include fees (and 1 wei offset)

    assert i != j and i < N_COINS and j < N_COINS, "coin index out of range"
    assert dy > 0, "do not exchange out 0 coins"

    math: ITwocryptoMath = staticcall ITwocrypto(swap).MATH()

    xp: uint256[N_COINS] = empty(uint256[N_COINS])
    precisions: uint256[N_COINS] = empty(uint256[N_COINS])
    price_scale: uint256 = 0
    D: uint256 = 0
    token_supply: uint256 = 0
    A: uint256 = 0
    gamma: uint256 = 0

    xp, D, token_supply, price_scale, A, gamma, precisions = self._prep_calc(swap)

    # adjust xp with output dy. dy contains fee element, which we handle later
    # (hence this internal method is called _get_dx_fee)
    xp[j] -= dy
    xp = [xp[0] * precisions[0], xp[1] * price_scale * precisions[1] // WAD]

    x_out: uint256[2] = staticcall math.get_y(A, gamma, xp, D, i)
    dx: uint256 = x_out[0] - xp[i]
    xp[i] = x_out[0]

    if i > 0:
        dx = dx * WAD // price_scale
    dx //= precisions[i]

    return dx, xp


@internal
@view
def _get_dy_nofee(
    i: uint256, j: uint256, dx: uint256, swap: address
) -> (uint256, uint256[N_COINS]):

    assert i != j and i < N_COINS and j < N_COINS, "coin index out of range"
    assert dx > 0, "do not exchange 0 coins"

    math: ITwocryptoMath = staticcall ITwocrypto(swap).MATH()

    xp: uint256[N_COINS] = empty(uint256[N_COINS])
    precisions: uint256[N_COINS] = empty(uint256[N_COINS])
    price_scale: uint256 = 0
    D: uint256 = 0
    token_supply: uint256 = 0
    A: uint256 = 0
    gamma: uint256 = 0

    xp, D, token_supply, price_scale, A, gamma, precisions = self._prep_calc(swap)

    # adjust xp with input dx
    xp[i] += dx
    xp = [
        xp[0] * precisions[0],
        xp[1] * price_scale * precisions[1] // WAD
    ]

    y_out: uint256[2] = staticcall math.get_y(A, gamma, xp, D, j)

    dy: uint256 = xp[j] - y_out[0] - 1
    xp[j] = y_out[0]
    if j > 0:
        dy = dy * WAD // price_scale
    dy //= precisions[j]

    return dy, xp


@internal
@view
def _calc_dtoken_nofee(
    amounts: uint256[N_COINS], deposit: bool, swap: address
) -> (uint256, uint256[N_COINS], uint256[N_COINS]):

    math: ITwocryptoMath = staticcall ITwocrypto(swap).MATH()

    xp: uint256[N_COINS] = empty(uint256[N_COINS])
    precisions: uint256[N_COINS] = empty(uint256[N_COINS])
    price_scale: uint256 = 0
    D0: uint256 = 0
    token_supply: uint256 = 0
    A: uint256 = 0
    gamma: uint256 = 0

    xp, D0, token_supply, price_scale, A, gamma, precisions = self._prep_calc(swap)

    amountsp: uint256[N_COINS] = amounts
    if deposit:
        for k: uint256 in range(N_COINS):
            xp[k] += amounts[k]
    else:
        for k: uint256 in range(N_COINS):
            xp[k] -= amounts[k]

    xp = [
        xp[0] * precisions[0],
        xp[1] * price_scale * precisions[1] // WAD
    ]
    amountsp = [
        amountsp[0] * precisions[0],
        amountsp[1] * price_scale * precisions[1] // WAD
    ]

    D: uint256 = staticcall math.newton_D(A, gamma, xp, 0)
    d_token: uint256 = token_supply * D // D0

    if deposit:
        d_token -= token_supply
    else:
        d_token = token_supply - d_token

    return d_token, amountsp, xp


@internal
@view
def _calc_withdraw_one_coin(
    token_amount: uint256,
    i: uint256,
    swap: address
) -> (uint256, uint256):

    token_supply: uint256 = staticcall ITwocrypto(swap).totalSupply()
    assert token_amount <= token_supply, "token amount more than supply"
    assert i < N_COINS, "coin out of range"

    math: ITwocryptoMath = staticcall ITwocrypto(swap).MATH()

    xx: uint256[N_COINS] = empty(uint256[N_COINS])
    for k: uint256 in range(N_COINS):
        xx[k] = staticcall ITwocrypto(swap).balances(k)

    precisions: uint256[N_COINS] = staticcall ITwocrypto(swap).precisions()
    A: uint256 = staticcall ITwocrypto(swap).A()
    gamma: uint256 = staticcall ITwocrypto(swap).gamma()
    D0: uint256 = 0
    p: uint256 = 0

    price_scale_i: uint256 = staticcall ITwocrypto(swap).price_scale() * precisions[1]
    xp: uint256[N_COINS] = [
        xx[0] * precisions[0],
        unsafe_div(xx[1] * price_scale_i, WAD)
    ]
    if i == 0:
        price_scale_i = WAD * precisions[0]

    if staticcall ITwocrypto(swap).future_A_gamma_time() > block.timestamp:
        D0 = staticcall math.newton_D(A, gamma, xp, 0)
    else:
        D0 = staticcall ITwocrypto(swap).D()

    D: uint256 = D0

    fee: uint256 = self._fee(xp, swap)
    dD: uint256 = token_amount * D // token_supply

    D_fee: uint256 = fee * dD // (2 * 10**10) + 1
    approx_fee: uint256 = N_COINS * D_fee * xx[i] // D

    D -= (dD - D_fee)

    y_out: uint256[2] = staticcall math.get_y(A, gamma, xp, D, i)
    dy: uint256 = (xp[i] - y_out[0]) * WAD // price_scale_i
    xp[i] = y_out[0]

    return dy, approx_fee


@internal
@view
def _fee(xp: uint256[N_COINS], swap: address) -> uint256:

    packed_fee_params: uint256 = staticcall ITwocrypto(swap).packed_fee_params()
    fee_params: uint256[3] = self._unpack_3(packed_fee_params)
    f: uint256 = xp[0] + xp[1]
    f = fee_params[2] * 10**18 // (
        fee_params[2] + 10**18 -
        (10**18 * N_COINS**N_COINS) * xp[0] // f * xp[1] // f
    )

    return (fee_params[0] * f + fee_params[1] * (10**18 - f)) // 10**18


@internal
@view
def _prep_calc(swap: address) -> (
    uint256[N_COINS],
    uint256,
    uint256,
    uint256,
    uint256,
    uint256,
    uint256[N_COINS]
):

    precisions: uint256[N_COINS] = staticcall ITwocrypto(swap).precisions()
    token_supply: uint256 = staticcall ITwocrypto(swap).totalSupply()
    xp: uint256[N_COINS] = empty(uint256[N_COINS])
    for k: uint256 in range(N_COINS):
        xp[k] = staticcall ITwocrypto(swap).balances(k)

    price_scale: uint256 = staticcall ITwocrypto(swap).price_scale()

    A: uint256 = staticcall ITwocrypto(swap).A()
    gamma: uint256 = staticcall ITwocrypto(swap).gamma()
    D: uint256 = self._calc_D_ramp(
        A, gamma, xp, precisions, price_scale, swap
    )

    return xp, D, token_supply, price_scale, A, gamma, precisions


@internal
@view
def _unpack_3(_packed: uint256) -> uint256[3]:
    """
    @notice Unpacks a uint256 into 3 integers (values must be <= 10**18)
    @param val The uint256 to unpack
    @return The unpacked uint256[3]
    """
    return [
        (_packed >> 128) & 18446744073709551615,
        (_packed >> 64) & 18446744073709551615,
        _packed & 18446744073709551615,
    ]
