# @version 0.3.9

# (c) Curve.Fi, 2020-2023
# AMM Math for 2-coin Curve Cryptoswap Pools
#
# Unless otherwise agreed on, only contracts owned by Curve DAO or
# Swiss Stake GmbH are allowed to call this contract.

"""
@title CurveTricryptoMathOptimized
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2023 - all rights reserved
@notice Curve AMM Math for 2 unpegged assets (e.g. ETH <> USD).
"""

N_COINS: constant(uint256) = 2
A_MULTIPLIER: constant(uint256) = 10000

MIN_GAMMA: constant(uint256) = 10**10
MAX_GAMMA: constant(uint256) = 5 * 10**16

MIN_A: constant(uint256) = N_COINS**N_COINS * A_MULTIPLIER / 10
MAX_A: constant(uint256) = N_COINS**N_COINS * A_MULTIPLIER * 100000

version: public(constant(String[8])) = "v2.0.0"


# ------------------------ AMM math functions --------------------------------


@internal
@pure
def _cbrt(x: uint256) -> uint256:

    # we artificially set a cap to the values for which we can compute the
    # cube roots safely. This is not to say that there are no values above
    # max(uint256) // 10**36 for which we cannot get good cube root estimates.
    # However, beyond this point, accuracy is not guaranteed since overflows
    # start to occur.
    # assert x < 115792089237316195423570985008687907853269, "inaccurate cbrt"  # TODO: check limits again

    # we increase precision of input `x` by multiplying 10 ** 36.
    # in such cases: cbrt(10**18) = 10**18, cbrt(1) = 10**12
    xx: uint256 = 0
    if x >= 115792089237316195423570985008687907853269 * 10**18:
        xx = x
    elif x >= 115792089237316195423570985008687907853269:
        xx = unsafe_mul(x, 10**18)
    else:
        xx = unsafe_mul(x, 10**36)

    # get log2(x) for approximating initial value
    # logic is: cbrt(a) = cbrt(2**(log2(a))) = 2**(log2(a) / 3) ≈ 2**|log2(a)/3|
    # from: https://github.com/transmissions11/solmate/blob/b9d69da49bbbfd090f1a73a4dba28aa2d5ee199f/src/utils/FixedPointMathLib.sol#L352

    a_pow: int256 = 0
    if xx > 340282366920938463463374607431768211455:
        a_pow = 128
    if unsafe_div(xx, shift(2, a_pow)) > 18446744073709551615:
        a_pow = a_pow | 64
    if unsafe_div(xx, shift(2, a_pow)) > 4294967295:
        a_pow = a_pow | 32
    if unsafe_div(xx, shift(2, a_pow)) > 65535:
        a_pow = a_pow | 16
    if unsafe_div(xx, shift(2, a_pow)) > 255:
        a_pow = a_pow | 8
    if unsafe_div(xx, shift(2, a_pow)) > 15:
        a_pow = a_pow | 4
    if unsafe_div(xx, shift(2, a_pow)) > 3:
        a_pow = a_pow | 2
    if unsafe_div(xx, shift(2, a_pow)) > 1:
        a_pow = a_pow | 1

    # initial value: 2**|log2(a)/3|
    # which is: 2 ** (n / 3) * 1260 ** (n % 3) / 1000 ** (n % 3)
    a_pow_mod: uint256 = convert(a_pow, uint256) % 3
    a: uint256 = unsafe_div(
        unsafe_mul(
            pow_mod256(
                2,
                unsafe_div(
                    convert(a_pow, uint256), 3
                )
            ),
            pow_mod256(1260, a_pow_mod)
        ),
        pow_mod256(1000, a_pow_mod)
    )

    # 7 newton raphson iterations:
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)

    if x >= 115792089237316195423570985008687907853269 * 10**18:
        return a*10**12
    elif x >= 115792089237316195423570985008687907853269:
        return a*10**6
    else:
        return a


@internal
@pure
def _newton_y(ANN: uint256, gamma: uint256, x: uint256[N_COINS], D: uint256, i: uint256) -> uint256:
    """
    Calculating x[i] given other balances x[0..N_COINS-1] and invariant D
    ANN = A * N**N
    """
    # Safety checks
    # assert ANN > MIN_A - 1 and ANN < MAX_A + 1  # dev: unsafe values A
    # assert gamma > MIN_GAMMA - 1 and gamma < MAX_GAMMA + 1  # dev: unsafe values gamma
    # assert D > 10**17 - 1 and D < 10**15 * 10**18 + 1 # dev: unsafe values D

    x_j: uint256 = x[1 - i]
    y: uint256 = D**2 / (x_j * N_COINS**2)
    K0_i: uint256 = (10**18 * N_COINS) * x_j / D
    # S_i = x_j

    # frac = x_j * 1e18 / D => frac = K0_i / N_COINS
    # assert (K0_i > 10**16*N_COINS - 1) and (K0_i < 10**20*N_COINS + 1)  # dev: unsafe values x[i]

    # x_sorted: uint256[N_COINS] = x
    # x_sorted[i] = 0
    # x_sorted = self.sort(x_sorted)  # From high to low
    # x[not i] instead of x_sorted since x_soted has only 1 element

    convergence_limit: uint256 = max(max(x_j / 10**14, D / 10**14), 100)

    for j in range(255):
        y_prev: uint256 = y

        K0: uint256 = K0_i * y * N_COINS / D
        S: uint256 = x_j + y

        _g1k0: uint256 = gamma + 10**18
        if _g1k0 > K0:
            _g1k0 = _g1k0 - K0 + 1
        else:
            _g1k0 = K0 - _g1k0 + 1

        # D / (A * N**N) * _g1k0**2 / gamma**2
        mul1: uint256 = 10**18 * D / gamma * _g1k0 / gamma * _g1k0 * A_MULTIPLIER / ANN

        # 2*K0 / _g1k0
        mul2: uint256 = 10**18 + (2 * 10**18) * K0 / _g1k0

        yfprime: uint256 = 10**18 * y + S * mul2 + mul1
        _dyfprime: uint256 = D * mul2
        if yfprime < _dyfprime:
            y = y_prev / 2
            continue
        else:
            yfprime -= _dyfprime
        fprime: uint256 = yfprime / y

        # y -= f / f_prime;  y = (y * fprime - f) / fprime
        # y = (yfprime + 10**18 * D - 10**18 * S) // fprime + mul1 // fprime * (10**18 - K0) // K0
        y_minus: uint256 = mul1 / fprime
        y_plus: uint256 = (yfprime + 10**18 * D) / fprime + y_minus * 10**18 / K0
        y_minus += 10**18 * S / fprime

        if y_plus < y_minus:
            y = y_prev / 2
        else:
            y = y_plus - y_minus

        diff: uint256 = 0
        if y > y_prev:
            diff = y - y_prev
        else:
            diff = y_prev - y
        if diff < max(convergence_limit, y / 10**14):
            frac: uint256 = y * 10**18 / D
            # assert (frac > 10**16 - 1) and (frac < 10**20 + 1)  # dev: unsafe value for y
            return y

    raise "Did not converge"

@external
@pure
def newton_y(ANN: uint256, gamma: uint256, x: uint256[N_COINS], D: uint256, i: uint256) -> uint256:
    return self._newton_y(ANN, gamma, x, D, i)


@external
@pure
def get_y(_ANN: uint256, _gamma: uint256, _x: uint256[N_COINS], _D: uint256, i: uint256) -> uint256[2]:

    # Safety checks go here

    j: uint256 = 0
    if i == 0:
        j = 1
    elif i == 1:
        j = 0

    ANN: int256 = convert(_ANN, int256)
    gamma: int256 = convert(_gamma, int256)
    D: int256 = convert(_D, int256)
    x_j: int256 = convert(_x[j], int256)
    gamma2: int256 = gamma**2

    a: int256 = 10**32
    b: int256 = ANN*D*gamma2/4/10000/x_j/10**4 - 10**32*3 - 2*gamma*10**14
    c: int256 = 10**32*3 + 4*gamma*10**14 + gamma2/10**4 + 4*ANN*gamma2*x_j/D/10000/4/10**4 - 4*ANN*gamma2/10000/4/10**4
    d: int256 = -(10**18+gamma)**2 / 10**4

    # delta0: int256 = 3*a*c/b - b
    delta0: int256 = unsafe_sub(unsafe_div(unsafe_mul(unsafe_mul(3, a), c), b), b)
    # delta1: int256 = 9*a*c/b - 2*b - 27*a**2/b*d/b
    delta1: int256 = unsafe_div(unsafe_mul(unsafe_mul(9, a), c), b) - unsafe_mul(2, b) - unsafe_div(unsafe_mul(unsafe_div(unsafe_mul(27, a**2), b), d), b)

    divider: int256 = 0
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
    else:
        divider = 1

    a = unsafe_div(a, divider)
    b = unsafe_div(b, divider)
    c = unsafe_div(c, divider)
    d = unsafe_div(d, divider)

    # delta0 = 3*a*c/b - b
    delta0 = unsafe_sub(unsafe_div(unsafe_mul(unsafe_mul(3, a), c), b), b)
    # delta1 = 9*a*c/b - 2*b - 27*a**2/b*d/b
    delta1 = unsafe_div(unsafe_mul(unsafe_mul(9, a), c), b) - unsafe_mul(2, b) - unsafe_div(unsafe_mul(unsafe_div(unsafe_mul(27, a**2), b), d), b)

    # sqrt_arg: int256 = delta1**2 + 4*delta0**2/b*delta0
    sqrt_arg: int256 = delta1**2 + unsafe_mul(unsafe_div(4*delta0**2, b), delta0)
    sqrt_val: int256 = 0
    if sqrt_arg > 0:
        sqrt_val = convert(isqrt(convert(sqrt_arg, uint256)), int256)
    else:
        return [self._newton_y(_ANN, _gamma, _x, _D, i), 0]

    b_cbrt: int256 = 0
    if b > 0:
        b_cbrt = convert(self._cbrt(convert(b, uint256)), int256)
    else:
        b_cbrt = -convert(self._cbrt(convert(-b, uint256)), int256)

    second_cbrt: int256 = 0
    if delta1 > 0:
        # second_cbrt = convert(self._cbrt(convert((delta1 + sqrt_val), uint256) / 2), int256)
        second_cbrt = convert(self._cbrt(convert(unsafe_add(delta1, sqrt_val), uint256) / 2), int256)
    else:
        # second_cbrt = -convert(self._cbrt(convert(unsafe_sub(sqrt_val, delta1), uint256) / 2), int256)
        second_cbrt = -convert(self._cbrt(unsafe_div(convert(unsafe_sub(sqrt_val, delta1), uint256), 2)), int256)

    # C1: int256 = b_cbrt**2/10**18*second_cbrt/10**18
    C1: int256 = unsafe_div(unsafe_mul(unsafe_div(b_cbrt**2, 10**18), second_cbrt), 10**18)

    # root: int256 = (10**18*C1 - 10**18*b - 10**18*b*delta0/C1)/(3*a), keep 2 safe ops here.
    root: int256 = (unsafe_mul(10**18, C1) - unsafe_mul(10**18, b) - unsafe_div(unsafe_mul(10**18, b)*delta0, C1))/unsafe_mul(3, a)

    # return [convert(D**2/x_j*root/4/10**18, uint256), convert(root, uint256)]
    return [convert(unsafe_div(unsafe_div(unsafe_mul(unsafe_div(D**2, x_j), root), 4), 10**18), uint256), convert(root, uint256)]


@internal
@pure
def geometric_mean(unsorted_x: uint256[N_COINS], sort: bool) -> uint256:
    """
    (x[0] * x[1] * ...) ** (1/N)
    """
    x: uint256[N_COINS] = unsorted_x
    if sort and x[0] < x[1]:
        x = [unsorted_x[1], unsorted_x[0]]
    D: uint256 = x[0]
    diff: uint256 = 0
    for i in range(255):
        D_prev: uint256 = D
        # tmp: uint256 = 10**18
        # for _x in x:
        #     tmp = tmp * _x / D
        # D = D * ((N_COINS - 1) * 10**18 + tmp) / (N_COINS * 10**18)
        # line below makes it for 2 coins
        D = unsafe_div(D + x[0] * x[1] / D, N_COINS)
        if D > D_prev:
            diff = unsafe_sub(D, D_prev)
        else:
            diff = unsafe_sub(D_prev, D)
        if diff <= 1 or diff * 10**18 < D:
            return D
    raise "Did not converge"


@external
@view
def newton_D(ANN: uint256, gamma: uint256, x_unsorted: uint256[N_COINS], K0_prev: uint256 = 0) -> uint256:
    """
    Finding the invariant using Newton method.
    ANN is higher by the factor A_MULTIPLIER
    ANN is already A * N**N

    Currently uses 60k gas
    """

    # Initial value of invariant D is that for constant-product invariant
    x: uint256[N_COINS] = x_unsorted
    if x[0] < x[1]:
        x = [x_unsorted[1], x_unsorted[0]]

    S: uint256 = x[0] + x[1]

    D: uint256 = 0
    if K0_prev == 0:
        D = N_COINS * isqrt(unsafe_mul(x[0], x[1]))
    else:
        # D = isqrt(x[0] * x[1] * 4 / K0_prev * 10**18)
        D = isqrt(unsafe_mul(unsafe_div(unsafe_mul(unsafe_mul(4, x[0]), x[1]), K0_prev), 10**18))
        if S < D:
            D = S

    __g1k0: uint256 = gamma + 10**18

    for i in range(255):
        D_prev: uint256 = D
        assert D > 0
        # Unsafe ivision by D is now safe

        # K0: uint256 = 10**18
        # for _x in x:
        #     K0 = K0 * _x * N_COINS / D
        # collapsed for 2 coins
        K0: uint256 = unsafe_div(unsafe_div((10**18 * N_COINS**2) * x[0], D) * x[1], D)

        _g1k0: uint256 = __g1k0
        if _g1k0 > K0:
            _g1k0 = unsafe_sub(_g1k0, K0) + 1  # > 0
        else:
            _g1k0 = unsafe_sub(K0, _g1k0) + 1  # > 0

        # D / (A * N**N) * _g1k0**2 / gamma**2
        mul1: uint256 = unsafe_div(unsafe_div(unsafe_div(10**18 * D, gamma) * _g1k0, gamma) * _g1k0 * A_MULTIPLIER, ANN)

        # 2*N*K0 / _g1k0
        mul2: uint256 = unsafe_div(((2 * 10**18) * N_COINS) * K0, _g1k0)

        neg_fprime: uint256 = (S + unsafe_div(S * mul2, 10**18)) + mul1 * N_COINS / K0 - unsafe_div(mul2 * D, 10**18)

        # D -= f / fprime
        D_plus: uint256 = D * (neg_fprime + S) / neg_fprime
        D_minus: uint256 = D*D / neg_fprime
        if 10**18 > K0:
            D_minus += unsafe_div(D * (mul1 / neg_fprime), 10**18) * unsafe_sub(10**18, K0) / K0
        else:
            D_minus -= unsafe_div(D * (mul1 / neg_fprime), 10**18) * unsafe_sub(K0, 10**18) / K0

        if D_plus > D_minus:
            D = unsafe_sub(D_plus, D_minus)
        else:
            D = unsafe_div(unsafe_sub(D_minus, D_plus), 2)

        diff: uint256 = 0
        if D > D_prev:
            diff = unsafe_sub(D, D_prev)
        else:
            diff = unsafe_sub(D_prev, D)
        if diff * 10**14 < max(10**16, D):  # Could reduce precision for gas efficiency here
            # Test that we are safe with the next newton_y
            for _x in x:
                frac: uint256 = _x * 10**18 / D
            return D

    raise "Did not converge"


@external
@view
def get_p(x_uint: uint256, y_uint: uint256, d_uint: uint256, gamma_uint: uint256, A_uint: uint256) -> uint256:

    x: int256 = convert(x_uint, int256)
    y: int256 = convert(y_uint, int256)
    d: int256 = convert(d_uint, int256)
    gamma: int256 = convert(gamma_uint, int256)
    A: int256 = convert(A_uint, int256)

    # s1: int256 = -10**18*64*x/d*x/d*x/d*y/d*y/d*y/d
    s1: int256 = - unsafe_div(unsafe_mul(unsafe_div(unsafe_mul(unsafe_div(unsafe_mul(unsafe_div(unsafe_mul(unsafe_div(unsafe_mul(unsafe_div(unsafe_mul(10**18*64, x), d), x), d), x), d), y), d), y), d), y), d)

    # s2: int256 = (10**18+gamma)*48*x/d*x/d*y/d*y/d
    s2: int256 = unsafe_div(unsafe_mul(unsafe_div(unsafe_mul(unsafe_div(unsafe_mul(unsafe_div(unsafe_mul(unsafe_add(10**18, gamma)*48, x), d), x), d), y), d), y), d)

    # s3: int256 = 4*A*(x + y)*(10**18 + gamma)/10**18*gamma/d*gamma/10**18/10000/4
    s3: int256 = unsafe_div(unsafe_div(unsafe_mul(unsafe_div(unsafe_mul(unsafe_div(unsafe_mul(unsafe_mul(4*A, unsafe_add(x, y)), unsafe_add(10**18, gamma)), 10**18), gamma), d), gamma), 10**18), 10000) / 4

    # s4: int256 = (10**18 + gamma)*((10**18 + gamma)**2/10**18 - 4*A*gamma**2/10000/4/10**18)/10**18
    s4: int256 = unsafe_div(unsafe_mul(unsafe_add(10**18, gamma), unsafe_div(unsafe_add(10**18, gamma)**2, 10**18) - unsafe_div(unsafe_div(unsafe_div(unsafe_mul(4*A, gamma**2), 10000), 4), 10**18)), 10**18)

    # s5: int256 = -4*x*y/d*(3*10**18 + 6*gamma + 3*gamma**2/10**18 + 4*A*gamma**2/10000/4/10**18)/d
    s5: int256 = -unsafe_div(unsafe_mul(unsafe_div(unsafe_mul(4*x, y), d), (3*10**18 + 6*gamma + unsafe_div(3*gamma**2, 10**18) + unsafe_div(unsafe_div(unsafe_mul(4*A, gamma**2), 10**18), 10000) / 4)), d)

    # a: int256 = s1 + s2 + s3 + s4 + s5
    a: int256 = unsafe_add(unsafe_add(unsafe_add(unsafe_add(s1, s2), s3), s4), s5)

    # b: int256 = 4 * A * (10**18 + gamma) * gamma / 10000 / 4 / d * gamma / 10**18
    b: int256 = unsafe_div(unsafe_div(unsafe_mul(unsafe_div(unsafe_mul(unsafe_mul(4*A, unsafe_add(10**18, gamma)), gamma), d), gamma), 10**18), 10000) / 4

    # c: int256 = 16 * A * x * y / d * gamma / d * gamma / d / 10000 / 4
    c: int256 = unsafe_div(unsafe_div(unsafe_mul(unsafe_div(unsafe_mul(unsafe_div(unsafe_mul(unsafe_mul(16*A, x), y), d), gamma), d), gamma), d), 10000) / 4

    # p: int256 = -(
    #     (10**18*a + b*x + c*y) / 10**18 * y
    # )/(
    #     (10**18*a + b*y + c*x) / 10**18 * x / 10**18
    # )
    p: int256 = -unsafe_mul(unsafe_div(unsafe_add(unsafe_add(unsafe_mul(10**18, a), unsafe_mul(b, x)), unsafe_mul(c, y)), 10**18), y) / unsafe_div(unsafe_mul(unsafe_div(unsafe_add(unsafe_add(unsafe_mul(10**18, a), unsafe_mul(b, y)), unsafe_mul(c, x)), 10**18), x), 10**18)

    return convert(-p, uint256)
