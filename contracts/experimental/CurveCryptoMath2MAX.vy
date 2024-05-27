# pragma version 0.3.10
# pragma optimize gas
# pragma evm-version paris


N_COINS: constant(uint256) = 2
A_MULTIPLIER: constant(uint256) = 10000

MIN_GAMMA: constant(uint256) = 10**10
MAX_GAMMA_SMALL: constant(uint256) = 2 * 10**16
MAX_GAMMA: constant(uint256) = 199 * 10**15 # 1.99 * 10**17

MIN_A: constant(uint256) = N_COINS**N_COINS * A_MULTIPLIER / 10
MAX_A: constant(uint256) = N_COINS**N_COINS * A_MULTIPLIER * 1000

MAX_ITER: constant(uint256) = 255


@external
@view
def newton_D() -> (
    uint256[MAX_ITER],
    uint256[MAX_ITER],
    uint256[MAX_ITER],
    uint256[MAX_ITER],
    uint256[MAX_ITER],
    uint256[MAX_ITER],
    uint256[MAX_ITER],
    uint256[MAX_ITER]
):
    """
    Finding the invariant using Newton method.
    ANN is higher by the factor A_MULTIPLIER
    ANN is already A * N**N
    """

    # # Safety checks
    # assert ANN > MIN_A - 1 and ANN < MAX_A + 1  # dev: unsafe values A
    # assert gamma > MIN_GAMMA - 1 and gamma < MAX_GAMMA + 1  # dev: unsafe values gamma

    # # Initial value of invariant D is that for constant-product invariant
    # x: uint256[N_COINS] = x_unsorted
    # if x[0] < x[1]:
    #     x = [x_unsorted[1], x_unsorted[0]]

    # assert x[0] > 10**9 - 1 and x[0] < 10**15 * 10**18 + 1  # dev: unsafe values x[0]
    # assert unsafe_div(x[1] * 10**18, x[0]) > 10**14 - 1  # dev: unsafe values x[i] (input)

    ANN: uint256 = MAX_A
    gamma: uint256 = MAX_GAMMA

    x: uint256[N_COINS] = [10**15 * 10**18, 10**15 * 10**18]
    S: uint256 = unsafe_add(x[0], x[1])  # can unsafe add here because we checked x[0] bounds
    D: uint256 = N_COINS * isqrt(unsafe_mul(x[0], x[1]))

    __g1k0: uint256 = gamma + 10**18
    diff: uint256 = 0

    K0_iter: uint256[MAX_ITER] = empty(uint256[MAX_ITER])
    _g1k0_iter: uint256[MAX_ITER] = empty(uint256[MAX_ITER])
    mul1_iter: uint256[MAX_ITER] = empty(uint256[MAX_ITER])
    mul2_iter: uint256[MAX_ITER] = empty(uint256[MAX_ITER])
    neg_fprime_iter: uint256[MAX_ITER] = empty(uint256[MAX_ITER])
    D_plus_iter: uint256[MAX_ITER] = empty(uint256[MAX_ITER])
    D_minus_iter: uint256[MAX_ITER] = empty(uint256[MAX_ITER])
    D_iter: uint256[MAX_ITER] = empty(uint256[MAX_ITER])

    for i in range(MAX_ITER):
        D_prev: uint256 = D
        assert D > 0
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
            # K0 is greater than 0
            # _g1k0 is greater than 0

        # D / (A * N**N) * _g1k0**2 / gamma**2
        mul1: uint256 = unsafe_div(unsafe_div(unsafe_div(10**18 * D, gamma) * _g1k0, gamma) * _g1k0 * A_MULTIPLIER, ANN)

        # 2*N*K0 / _g1k0
        mul2: uint256 = unsafe_div(((2 * 10**18) * N_COINS) * K0, _g1k0)

        # calculate neg_fprime. here K0 > 0 is being validated (safediv).
        neg_fprime: uint256 = (
            S +
            unsafe_div(S * mul2, 10**18) +
            mul1 * N_COINS / K0 -
            unsafe_div(mul2 * D, 10**18)
        )

        # D -= f / fprime; neg_fprime safediv being validated
        D_plus: uint256 = D * (neg_fprime + S) / neg_fprime
        D_minus: uint256 = unsafe_div(D * D,  neg_fprime)
        if 10**18 > K0:
            D_minus += unsafe_div(unsafe_div(D * unsafe_div(mul1, neg_fprime), 10**18) * unsafe_sub(10**18, K0), K0)
        else:
            D_minus -= unsafe_div(unsafe_div(D * unsafe_div(mul1, neg_fprime), 10**18) * unsafe_sub(K0, 10**18), K0)

        if D_plus > D_minus:
            D = unsafe_sub(D_plus, D_minus)
        else:
            D = unsafe_div(unsafe_sub(D_minus, D_plus), 2)

        K0_iter[i] = K0
        _g1k0_iter[i] = _g1k0
        mul1_iter[i] = mul1
        mul2_iter[i] = mul2
        neg_fprime_iter[i] = neg_fprime
        D_plus_iter[i] = D_plus
        D_minus_iter[i] = D_minus
        D_iter[i] = D

    return K0_iter, _g1k0_iter, mul1_iter, mul2_iter, neg_fprime_iter, D_plus_iter, D_minus_iter, D_iter
