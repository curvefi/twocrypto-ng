# pragma version ~=0.4.0
# Minimized version of the math contracts that expose some inner details of newton_y for testing purposes:
# - Additionally to the final value it also returns the number of iterations it took to find the value.
# From commit: 6dec22f6956cc04fb865d93c1e521f146e066cab

N_COINS: constant(uint256) = 2
A_MULTIPLIER: constant(uint256) = 10000

MIN_GAMMA: constant(uint256) = 10**10
MAX_GAMMA: constant(uint256) = 3 * 10**17

MIN_A: constant(uint256) = N_COINS**N_COINS * A_MULTIPLIER // 10
MAX_A: constant(uint256) = N_COINS**N_COINS * A_MULTIPLIER * 1000

@internal
@pure
def _newton_y(ANN: uint256, gamma: uint256, x: uint256[N_COINS], D: uint256, i: uint256, lim_mul: uint256) -> (uint256, uint256):
    """
    Calculating x[i] given other balances x[0..N_COINS-1] and invariant D
    ANN = A * N**N
    This is computationally expensive.
    """

    x_j: uint256 = x[1 - i]
    y: uint256 = D**2 // (x_j * N_COINS**2)
    K0_i: uint256 = (10**18 * N_COINS) * x_j // D

    assert (K0_i >= unsafe_div(10**36, lim_mul)) and (K0_i <= lim_mul)  # dev: unsafe values x[i]

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

        # y -= f // f_prime;  y = (y * fprime - f) // fprime
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
            return y, j

    raise "Did not converge"
