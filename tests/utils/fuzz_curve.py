# flake8: noqa

"""
This file was originally used to find the initial bounds for A and gamma in the Curve contract.
It is now used to test contract with Hypothesis stateful testing. Some unused parts are broken
and kept for reference.

Original file: https://github.com/curvefi/curve-crypto-contract/blob/d7d04cd9ae038970e40be850df99de8c1ff7241b/tests/simulation_int_many.py
"""

from itertools import permutations

import hypothesis.strategies as st
from hypothesis import given, settings

from tests.utils.simulator import (
    Curve,
    geometric_mean,
    reduction_coefficient,
    solve_D,
    solve_x,
)

MAX_EXAMPLES_MEAN = 20000
MAX_EXAMPLES_RED = 20000
MAX_EXAMPLES_D = 10000
MAX_EXAMPLES_Y = 5000
MAX_EXAMPLES_YD = 100000
MAX_EXAMPLES_NOLOSS = 100000
MIN_FEE = 5e-5

MIN_XD = 10**16
MAX_XD = 10**20

N_COINS = 2
A_MUL = 10000
MIN_A = int(N_COINS**N_COINS * A_MUL / 10)
MAX_A = int(N_COINS**N_COINS * A_MUL * 1000)

MIN_GAMMA = 10**10
MAX_GAMMA = 2 * 10**15


# Test with 2 coins
@given(
    x=st.integers(10**9, 10**15 * 10**18),
    y=st.integers(10**9, 10**15 * 10**18),
)
@settings(max_examples=MAX_EXAMPLES_MEAN)
def test_geometric_mean(x, y):
    val = geometric_mean([x, y])
    assert val > 0
    diff = abs((x * y) ** (1 / 2) - val)
    assert diff / val <= max(1e-10, 1 / min([x, y]))


@given(
    x=st.integers(10**9, 10**15 * 10**18),
    y=st.integers(10**9, 10**15 * 10**18),
    gamma=st.integers(10**10, 10**18),
)
@settings(max_examples=MAX_EXAMPLES_RED)
def test_reduction_coefficient(x, y, gamma):
    coeff = reduction_coefficient([x, y], gamma)
    assert coeff <= 10**18

    K = 2**2 * x * y / (x + y) ** 2
    if gamma > 0:
        K = (gamma / 1e18) / ((gamma / 1e18) + 1 - K)
    assert abs(coeff / 1e18 - K) <= 1e-7


@given(
    A=st.integers(MIN_A, MAX_A),
    x=st.integers(10**18, 10**15 * 10**18),  # 1 USD to 1e15 USD
    yx=st.integers(10**14, 10**18),  # <- ratio 1e18 * y/x, typically 1e18 * 1
    perm=st.integers(0, 1),  # <- permutation mapping to values
    gamma=st.integers(MIN_GAMMA, MAX_GAMMA),
)
@settings(max_examples=MAX_EXAMPLES_D)
def test_D_convergence(A, x, yx, perm, gamma):
    # Price not needed for convergence testing
    pmap = list(permutations(range(2)))

    y = x * yx // 10**18
    curve = Curve(A, gamma, 10**18, p)
    curve.x = [0] * 2
    i, j = pmap[perm]
    curve.x[i] = x
    curve.x[j] = y
    assert curve.D() > 0


@given(
    A=st.integers(MIN_A, MAX_A),
    x=st.integers(10**17, 10**15 * 10**18),  # $0.1 .. $1e15
    yx=st.integers(10**15, 10**21),
    gamma=st.integers(MIN_GAMMA, MAX_GAMMA),
    i=st.integers(0, 1),
    inx=st.integers(10**15, 10**21),
)
@settings(max_examples=MAX_EXAMPLES_Y)
def test_y_convergence(A, x, yx, gamma, i, inx):
    j = 1 - i
    in_amount = x * inx // 10**18
    y = x * yx // 10**18
    curve = Curve(A, gamma, 10**18, p)
    curve.x = [x, y]
    out_amount = curve.y(in_amount, i, j)
    assert out_amount > 0


@given(
    A=st.integers(MIN_A, MAX_A),
    x=st.integers(10**17, 10**15 * 10**18),  # 0.1 USD to 1e15 USD
    yx=st.integers(5 * 10**14, 20 * 10**20),
    gamma=st.integers(MIN_GAMMA, MAX_GAMMA),
    i=st.integers(0, 1),
    inx=st.integers(3 * 10**15, 3 * 10**20),
)
@settings(max_examples=MAX_EXAMPLES_NOLOSS)
def test_y_noloss(A, x, yx, gamma, i, inx):
    j = 1 - i
    y = x * yx // 10**18
    curve = Curve(A, gamma, 10**18, p)
    curve.x = [x, y]
    in_amount = x * inx // 10**18
    try:
        out_amount = curve.y(in_amount, i, j)
        D1 = curve.D()
    except ValueError:
        return  # Convergence checked separately - we deliberately try unsafe numbers
    is_safe = all(f >= MIN_XD and f <= MAX_XD for f in [xx * 10**18 // D1 for xx in curve.x])
    curve.x[i] = in_amount
    curve.x[j] = out_amount
    try:
        D2 = curve.D()
    except ValueError:
        return  # Convergence checked separately - we deliberately try unsafe numbers
    is_safe &= all(f >= MIN_XD and f <= MAX_XD for f in [xx * 10**18 // D2 for xx in curve.x])
    if is_safe:
        assert 2 * (D1 - D2) / (D1 + D2) < MIN_FEE  # Only loss is prevented - gain is ok


@given(
    A=st.integers(MIN_A, MAX_A),
    D=st.integers(10**18, 10**15 * 10**18),  # 1 USD to 1e15 USD
    xD=st.integers(MIN_XD, MAX_XD),
    yD=st.integers(MIN_XD, MAX_XD),
    gamma=st.integers(MIN_GAMMA, MAX_GAMMA),
    j=st.integers(0, 1),
)
@settings(max_examples=MAX_EXAMPLES_YD)
def test_y_from_D(A, D, xD, yD, gamma, j):
    xp = [D * xD // 10**18, D * yD // 10**18]
    y = solve_x(A, gamma, xp, D, j)
    xp[j] = y
    D2 = solve_D(A, gamma, xp)
    assert 2 * (D - D2) / (D2 + D) < MIN_FEE  # Only loss is prevented - gain is ok
