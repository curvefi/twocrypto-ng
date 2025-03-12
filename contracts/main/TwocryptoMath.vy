# pragma version ~=0.4.1
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

MIN_GAMMA: constant(uint256) = 10**10
MAX_GAMMA_SMALL: constant(uint256) = 2 * 10**16
MAX_GAMMA: constant(uint256) = 199 * 10**15 # 1.99 * 10**17

MIN_A: constant(uint256) = N_COINS**N_COINS * A_MULTIPLIER // 10
MAX_A: constant(uint256) = N_COINS**N_COINS * A_MULTIPLIER * 1000

version: public(constant(String[8])) = "v2.1.0"


# ------------------------ AMM math functions --------------------------------


@internal
@pure
def _snekmate_log_2(x: uint256, roundup: bool) -> uint256:
    """
    @notice An `internal` helper function that returns the log in base 2
         of `x`, following the selected rounding direction.
    @dev This implementation is derived from Snekmate, which is authored
         by pcaversaccio (Snekmate), distributed under the AGPL-3.0 license.
         https://github.com/pcaversaccio/snekmate
    @dev Note that it returns 0 if given 0. The implementation is
         inspired by OpenZeppelin's implementation here:
         https://github.com/OpenZeppelin/openzeppelin-contracts/blob/master/contracts/utils/math/Math.sol.
    @param x The 32-byte variable.
    @param roundup The Boolean variable that specifies whether
           to round up or not. The default `False` is round down.
    @return uint256 The 32-byte calculation result.
    """
    value: uint256 = x
    result: uint256 = empty(uint256)

    # The following lines cannot overflow because we have the well-known
    # decay behaviour of `log_2(max_value(uint256)) < max_value(uint256)`.
    if x >> 128 != empty(uint256):
        value = x >> 128
        result = 128
    if value >> 64 != empty(uint256):
        value = value >> 64
        result = unsafe_add(result, 64)
    if value >> 32 != empty(uint256):
        value = value >> 32
        result = unsafe_add(result, 32)
    if value >> 16 != empty(uint256):
        value = value >> 16
        result = unsafe_add(result, 16)
    if value >> 8 != empty(uint256):
        value = value >> 8
        result = unsafe_add(result, 8)
    if value >> 4 != empty(uint256):
        value = value >> 4
        result = unsafe_add(result, 4)
    if value >> 2 != empty(uint256):
        value = value >> 2
        result = unsafe_add(result, 2)
    if value >> 1 != empty(uint256):
        result = unsafe_add(result, 1)

    if (roundup and (1 << result) < x):
        result = unsafe_add(result, 1)

    return result


@internal
@pure
def _cbrt(x: uint256) -> uint256:

    xx: uint256 = 0
    if x >= 115792089237316195423570985008687907853269 * 10**18:
        xx = x
    elif x >= 115792089237316195423570985008687907853269:
        xx = unsafe_mul(x, 10**18)
    else:
        xx = unsafe_mul(x, 10**36)

    log2x: int256 = convert(self._snekmate_log_2(xx, False), int256)

    # When we divide log2x by 3, the remainder is (log2x % 3).
    # So if we just multiply 2**(log2x/3) and discard the remainder to calculate our
    # guess, the newton method will need more iterations to converge to a solution,
    # since it is missing that precision. It's a few more calculations now to do less
    # calculations later:
    # pow = log2(x) // 3
    # remainder = log2(x) % 3
    # initial_guess = 2 ** pow * cbrt(2) ** remainder
    # substituting -> 2 = 1.26 ≈ 1260 / 1000, we get:
    #
    # initial_guess = 2 ** pow * 1260 ** remainder // 1000 ** remainder

    remainder: uint256 = convert(log2x, uint256) % 3
    a: uint256 = unsafe_div(
        unsafe_mul(
            pow_mod256(2, unsafe_div(convert(log2x, uint256), 3)),  # <- pow
            pow_mod256(1260, remainder),
        ),
        pow_mod256(1000, remainder),
    )

    # Because we chose good initial values for cube roots, 7 newton raphson iterations
    # are just about sufficient. 6 iterations would result in non-convergences, and 8
    # would be one too many iterations. Without initial values, the iteration count
    # can go up to 20 or greater. The iterations are unrolled. This reduces gas costs
    # but takes up more bytecode:
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)

    if x >= 115792089237316195423570985008687907853269 * 10**18:
        a = unsafe_mul(a, 10**12)
    elif x >= 115792089237316195423570985008687907853269:
        a = unsafe_mul(a, 10**6)

    return a


@internal
@pure
def _newton_y(ANN: uint256, gamma: uint256, x: uint256[N_COINS], D: uint256, i: uint256, lim_mul: uint256) -> uint256:
    """
    Calculating x[i] given other balances x[0..N_COINS-1] and invariant D
    ANN = A * N**N
    This is computationally expensive.
    """

    x_j: uint256 = x[1 - i]
    y: uint256 = D**2 // (x_j * N_COINS**2)
    K0_i: uint256 = (10**18 * N_COINS) * x_j // D

    assert (K0_i >= unsafe_div(10**36, lim_mul)) and (K0_i <= lim_mul), "unsafe values x[i]"

    convergence_limit: uint256 = max(max(x_j // 10**14, D // 10**14), 100)

    for j: uint256 in range(255):
        y_prev: uint256 = y

        K0: uint256 = K0_i * y * N_COINS // D
        S: uint256 = x_j + y

        _g1k0: uint256 = gamma + 10**18
        if _g1k0 > K0:
            _g1k0 = _g1k0 - K0 + 1
        else:
            _g1k0 = K0 - _g1k0 + 1

        # D / (A * N**N) * _g1k0**2 / gamma**2
        mul1: uint256 = 10**18 * D // gamma * _g1k0 // gamma * _g1k0 * A_MULTIPLIER // ANN

        # 2*K0 / _g1k0
        mul2: uint256 = 10**18 + (2 * 10**18) * K0 // _g1k0

        yfprime: uint256 = 10**18 * y + S * mul2 + mul1
        _dyfprime: uint256 = D * mul2
        if yfprime < _dyfprime:
            y = y_prev // 2
            continue
        else:
            yfprime -= _dyfprime
        fprime: uint256 = yfprime // y

        # y -= f / f_prime;  y = (y * fprime - f) / fprime
        # y = (yfprime + 10**18 * D - 10**18 * S) // fprime + mul1 // fprime * (10**18 - K0) // K0
        y_minus: uint256 = mul1 // fprime
        y_plus: uint256 = (yfprime + 10**18 * D) // fprime + y_minus * 10**18 // K0
        y_minus += 10**18 * S // fprime

        if y_plus < y_minus:
            y = y_prev // 2
        else:
            y = y_plus - y_minus

        diff: uint256 = 0
        if y > y_prev:
            diff = y - y_prev
        else:
            diff = y_prev - y

        if diff < max(convergence_limit, y // 10**14):
            return y

    raise "Did not converge"


@external
@pure
def newton_y(ANN: uint256, gamma: uint256, x: uint256[N_COINS], D: uint256, i: uint256) -> uint256:

    # Safety checks
    assert ANN > MIN_A - 1 and ANN < MAX_A + 1, "unsafe values A"
    assert gamma > MIN_GAMMA - 1 and gamma < MAX_GAMMA + 1, "unsafe values gamma"
    assert D > 10**17 - 1 and D < 10**15 * 10**18 + 1, "unsafe values D"
    lim_mul: uint256 = 100 * 10**18  # 100.0
    if gamma > MAX_GAMMA_SMALL:
        lim_mul = unsafe_div(unsafe_mul(lim_mul, MAX_GAMMA_SMALL), gamma)  # smaller than 100.0

    y: uint256 = self._newton_y(ANN, gamma, x, D, i, lim_mul)
    frac: uint256 = y * 10**18 // D
    assert (frac >= unsafe_div(10**36 // N_COINS, lim_mul)) and (frac <= unsafe_div(lim_mul, N_COINS)), "unsafe value for y"

    return y


@external
@pure
def get_y(
    _ANN: uint256,
    _gamma: uint256,
    _x: uint256[N_COINS],
    _D: uint256,
    i: uint256
) -> uint256[2]:

    # Safety checks
    assert _ANN > MIN_A - 1 and _ANN < MAX_A + 1, "unsafe values A"
    assert _gamma > MIN_GAMMA - 1 and _gamma < MAX_GAMMA + 1, "unsafe values gamma"
    assert _D > 10**17 - 1 and _D < 10**15 * 10**18 + 1, "unsafe values D"
    lim_mul: uint256 = 100 * 10**18  # 100.0
    if _gamma > MAX_GAMMA_SMALL:
        lim_mul = unsafe_div(unsafe_mul(lim_mul, MAX_GAMMA_SMALL), _gamma)  # smaller than 100.0
    lim_mul_signed: int256 = convert(lim_mul, int256)

    ANN: int256 = convert(_ANN, int256)
    gamma: int256 = convert(_gamma, int256)
    D: int256 = convert(_D, int256)
    x_j: int256 = convert(_x[1 - i], int256)
    gamma2: int256 = unsafe_mul(gamma, gamma)

    # savediv by x_j done here:
    y: int256 = D**2 // (x_j * convert(N_COINS, int256)**2)

    # K0_i: int256 = (10**18 * N_COINS) * x_j / D
    K0_i: int256 = unsafe_div(10**18 * convert(N_COINS, int256) * x_j, D)
    assert (K0_i >= unsafe_div(10**36, lim_mul_signed)) and (K0_i <= lim_mul_signed), "unsafe values x[i]"

    ann_gamma2: int256 = ANN * gamma2

    # a = 10**36 / N_COINS**2
    a: int256 = 10**32

    # b = ANN*D*gamma2/4/10000/x_j/10**4 - 10**32*3 - 2*gamma*10**14
    b: int256 = (
        D*ann_gamma2//400000000//x_j
        - (3 * 10**32)
        - unsafe_mul(unsafe_mul(2, gamma), 10**14)
    )

    # c = 10**32*3 + 4*gamma*10**14 + gamma2/10**4 + 4*ANN*gamma2*x_j/D/10000/4/10**4 - 4*ANN*gamma2/10000/4/10**4
    c: int256 = (
        unsafe_mul(10**32, convert(3, int256))
        + unsafe_mul(unsafe_mul(4, gamma), 10**14)
        + unsafe_div(gamma2, 10**4)
        + unsafe_div(unsafe_div(unsafe_mul(4, ann_gamma2), 400000000) * x_j, D)
        - unsafe_div(unsafe_mul(4, ann_gamma2), 400000000)
    )

    # d = -(10**18+gamma)**2 / 10**4
    d: int256 = -unsafe_div(unsafe_add(10**18, gamma) ** 2, 10**4)

    # delta0: int256 = 3*a*c/b - b
    delta0: int256 = 3 * a * c // b - b  # safediv by b

    # delta1: int256 = 9*a*c/b - 2*b - 27*a**2/b*d/b
    delta1: int256 = 3 * delta0 + b - 27*a**2//b*d//b

    divider: int256 = 1
    threshold: int256 = min(min(abs(delta0), abs(delta1)), a)
    if threshold > 10**48:
        divider = 10**30
    elif threshold > 10**46:
        divider = 10**28
    elif threshold > 10**44:
        divider = 10**26
    elif threshold > 10**42:
        divider = 10**24
    elif threshold > 10**40:
        divider = 10**22
    elif threshold > 10**38:
        divider = 10**20
    elif threshold > 10**36:
        divider = 10**18
    elif threshold > 10**34:
        divider = 10**16
    elif threshold > 10**32:
        divider = 10**14
    elif threshold > 10**30:
        divider = 10**12
    elif threshold > 10**28:
        divider = 10**10
    elif threshold > 10**26:
        divider = 10**8
    elif threshold > 10**24:
        divider = 10**6
    elif threshold > 10**20:
        divider = 10**2

    a = unsafe_div(a, divider)
    b = unsafe_div(b, divider)
    c = unsafe_div(c, divider)
    d = unsafe_div(d, divider)

    # delta0 = 3*a*c/b - b: here we can do more unsafe ops now:
    delta0 = unsafe_div(unsafe_mul(unsafe_mul(3, a), c), b) - b

    # delta1 = 9*a*c/b - 2*b - 27*a**2/b*d/b
    delta1 = 3 * delta0 + b - unsafe_div(unsafe_mul(unsafe_div(unsafe_mul(27, a**2), b), d), b)

    # sqrt_arg: int256 = delta1**2 + 4*delta0**2/b*delta0
    sqrt_arg: int256 = delta1**2 + unsafe_mul(unsafe_div(4*delta0**2, b), delta0)
    sqrt_val: int256 = 0
    if sqrt_arg > 0:
        sqrt_val = convert(isqrt(convert(sqrt_arg, uint256)), int256)
    else:
        return [
            self._newton_y(_ANN, _gamma, _x, _D, i, lim_mul),
            0
        ]

    b_cbrt: int256 = 0
    if b > 0:
        b_cbrt = convert(self._cbrt(convert(b, uint256)), int256)
    else:
        b_cbrt = -convert(self._cbrt(convert(-b, uint256)), int256)

    second_cbrt: int256 = 0
    if delta1 > 0:
        # second_cbrt = convert(self._cbrt(convert((delta1 + sqrt_val), uint256) / 2), int256)
        second_cbrt = convert(self._cbrt(convert(unsafe_add(delta1, sqrt_val), uint256) // 2), int256)
    else:
        # second_cbrt = -convert(self._cbrt(convert(unsafe_sub(sqrt_val, delta1), uint256) / 2), int256)
        second_cbrt = -convert(self._cbrt(unsafe_div(convert(unsafe_sub(sqrt_val, delta1), uint256), 2)), int256)

    # C1: int256 = b_cbrt**2/10**18*second_cbrt/10**18
    C1: int256 = unsafe_div(unsafe_mul(unsafe_div(b_cbrt**2, 10**18), second_cbrt), 10**18)

    # root: int256 = (10**18*C1 - 10**18*b - 10**18*b*delta0/C1)/(3*a), keep 2 safe ops here.
    root: int256 = (unsafe_mul(10**18, C1) - unsafe_mul(10**18, b) - unsafe_mul(10**18, b)//C1*delta0)//unsafe_mul(3, a)

    # y_out: uint256[2] =  [
    #     convert(D**2/x_j*root/4/10**18, uint256),   # <--- y
    #     convert(root, uint256)  # <----------------------- K0Prev
    # ]
    y_out: uint256[2] = [convert(unsafe_div(unsafe_div(unsafe_mul(unsafe_div(D**2, x_j), root), 4), 10**18), uint256), convert(root, uint256)]

    frac: uint256 = unsafe_div(y_out[0] * 10**18, _D)
    assert (frac >= unsafe_div(10**36 // N_COINS, lim_mul)) and (frac <= unsafe_div(lim_mul, N_COINS)), "unsafe value for y"

    return y_out


@external
@view
def newton_D(ANN: uint256, gamma: uint256, x_unsorted: uint256[N_COINS], K0_prev: uint256 = 0) -> uint256:
    """
    Finding the invariant using Newton method.
    ANN is higher by the factor A_MULTIPLIER
    ANN is already A * N**N
    """

    # Safety checks
    assert ANN > MIN_A - 1 and ANN < MAX_A + 1, "unsafe values A"
    assert gamma > MIN_GAMMA - 1 and gamma < MAX_GAMMA + 1, "unsafe values gamma"

    # Initial value of invariant D is that for constant-product invariant
    x: uint256[N_COINS] = x_unsorted
    if x[0] < x[1]:
        x = [x_unsorted[1], x_unsorted[0]]

    assert x[0] > 10**9 - 1 and x[0] < 10**15 * 10**18 + 1, "unsafe values x[0]"
    assert unsafe_div(x[1] * 10**18, x[0]) > 10**14 - 1, "unsafe values x[i] (input)"

    S: uint256 = unsafe_add(x[0], x[1])  # can unsafe add here because we checked x[0] bounds

    D: uint256 = 0
    if K0_prev == 0:
        D = N_COINS * isqrt(unsafe_mul(x[0], x[1]))
    else:
        # D = isqrt(x[0] * x[1] * 4 / K0_prev * 10**18)
        D = isqrt(unsafe_mul(unsafe_div(unsafe_mul(unsafe_mul(4, x[0]), x[1]), K0_prev), 10**18))
        if S < D:
            D = S

    __g1k0: uint256 = gamma + 10**18
    diff: uint256 = 0

    for i: uint256 in range(255):
        D_prev: uint256 = D
        assert D > 0, "D==0"
        # Unsafe division by D and D_prev is now safe

        # K0: uint256 = 10**18
        # for _x in x:
        #     K0 = K0 * _x * N_COINS / D
        # collapsed for 2 coins
        K0: uint256 = unsafe_div(unsafe_div((10**18 * N_COINS**2) * x[0], D) * x[1], D)

        _g1k0: uint256 = __g1k0
        if _g1k0 > K0:
            _g1k0 = unsafe_add(unsafe_sub(_g1k0, K0), 1)  # > 0
        else:
            _g1k0 = unsafe_add(unsafe_sub(K0, _g1k0), 1)  # > 0

        # D / (A * N**N) * _g1k0**2 / gamma**2
        mul1: uint256 = unsafe_div(unsafe_div(unsafe_div(10**18 * D, gamma) * _g1k0, gamma) * _g1k0 * A_MULTIPLIER, ANN)

        # 2*N*K0 / _g1k0
        mul2: uint256 = unsafe_div(((2 * 10**18) * N_COINS) * K0, _g1k0)

        # calculate neg_fprime. here K0 > 0 is being validated (safediv).
        neg_fprime: uint256 = (S + unsafe_div(S * mul2, 10**18)) + mul1 * N_COINS // K0 - unsafe_div(mul2 * D, 10**18)

        # D -= f / fprime; neg_fprime safediv being validated
        D_plus: uint256 = D * (neg_fprime + S) // neg_fprime
        D_minus: uint256 = unsafe_div(D * D,  neg_fprime)
        if 10**18 > K0:
            D_minus += unsafe_div(unsafe_div(D * unsafe_div(mul1, neg_fprime), 10**18) * unsafe_sub(10**18, K0), K0)
        else:
            D_minus -= unsafe_div(unsafe_div(D * unsafe_div(mul1, neg_fprime), 10**18) * unsafe_sub(K0, 10**18), K0)

        if D_plus > D_minus:
            D = unsafe_sub(D_plus, D_minus)
        else:
            D = unsafe_div(unsafe_sub(D_minus, D_plus), 2)

        if D > D_prev:
            diff = unsafe_sub(D, D_prev)
        else:
            diff = unsafe_sub(D_prev, D)

        if diff * 10**14 < max(10**16, D):  # Could reduce precision for gas efficiency here

            for _x: uint256 in x:
                frac: uint256 = _x * 10**18 // D
                assert (frac > 10**16 // N_COINS - 1) and (frac < 10**20 // N_COINS + 1), "unsafe values x[i]"
            return D

    raise "Did not converge"


@external
@view
def get_p(
    _xp: uint256[N_COINS], _D: uint256, _A_gamma: uint256[N_COINS]
) -> uint256:
    """
    @notice Calculates dx/dy.
    @dev Output needs to be multiplied with price_scale to get the actual value.
    @param _xp Balances of the pool.
    @param _D Current value of D.
    @param _A_gamma Amplification coefficient and gamma.
    """

    assert _D > 10**17 - 1 and _D < 10**15 * 10**18 + 1, "unsafe D values"

    # K0 = P * N**N / D**N.
    # K0 is dimensionless and has 10**36 precision:
    K0: uint256 = unsafe_div(
        unsafe_div(4 * _xp[0] * _xp[1], _D) * 10**36,
        _D
    )

    # GK0 is in 10**36 precision and is dimensionless.
    # GK0 = (
    #     2 * _K0 * _K0 / 10**36 * _K0 / 10**36
    #     + (gamma + 10**18)**2
    #     - (_K0 * _K0 / 10**36 * (2 * gamma + 3 * 10**18) / 10**18)
    # )
    # GK0 is always positive. So the following should never revert:
    GK0: uint256 = (
        unsafe_div(unsafe_div(2 * K0 * K0, 10**36) * K0, 10**36)
        + pow_mod256(unsafe_add(_A_gamma[1], 10**18), 2)
        - unsafe_div(
            unsafe_div(pow_mod256(K0, 2), 10**36) * unsafe_add(unsafe_mul(2, _A_gamma[1]), 3 * 10**18),
            10**18
        )
    )

    # NNAG2 = N**N * A * gamma**2
    NNAG2: uint256 = unsafe_div(unsafe_mul(_A_gamma[0], pow_mod256(_A_gamma[1], 2)), A_MULTIPLIER)

    # denominator = (GK0 + NNAG2 * x / D * _K0 / 10**36)
    denominator: uint256 = (GK0 + unsafe_div(unsafe_div(NNAG2 * _xp[0], _D) * K0, 10**36) )

    # p_xy = x * (GK0 + NNAG2 * y / D * K0 / 10**36) / y * 10**18 / denominator
    # p is in 10**18 precision.
    return unsafe_div(
        _xp[0] * ( GK0 + unsafe_div(unsafe_div(NNAG2 * _xp[1], _D) * K0, 10**36) ) // _xp[1] * 10**18,
        denominator
    )


@external
@pure
def wad_exp(x: int256) -> int256:
    return math._wad_exp(x)
