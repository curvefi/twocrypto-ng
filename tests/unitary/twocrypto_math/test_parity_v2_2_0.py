"""
TwocryptoMath against the v2.2.0 cryptoswap math it was copied from.

tests/reference/CurveCryptoMathOptimized2.vy is a byte-identical copy of the
v2.2.0 math (twocrypto-ng commit 7b4fd90). TwocryptoMath replaced its local
log2, cube-root and exponential helpers with snekmate's and returns wad_exp as
uint256; the solver code is unchanged. These tests require identical outputs on
random inputs, and a revert in TwocryptoMath exactly where the reference reverts.
"""

import math as pymath
import random

import boa
import pytest

from tests.utils.constants import MAX_A, MAX_GAMMA, MAX_GAMMA_SMALL, MIN_A, MIN_GAMMA

REFERENCE_MATH = "tests/reference/CurveCryptoMathOptimized2.vy"

N_CHUNKS = 8  # separate seeds, so xdist can spread the work
CASES_PER_CHUNK = 40

MIN_D = 10**17
MAX_D = 10**33

WAD_EXP_ZERO_CUTOFF_REFERENCE = -42_139_678_854_452_767_551
WAD_EXP_ZERO_CUTOFF_SNEKMATE = -41_446_531_673_892_822_313
WAD_EXP_OVERFLOW = 135_305_999_368_893_231_589

GAMMA_EDGES = [
    MIN_GAMMA,
    11111111111,
    145 * 10**12,
    MAX_GAMMA_SMALL - 1,
    MAX_GAMMA_SMALL,
    MAX_GAMMA_SMALL + 1,
    MAX_GAMMA,
]


@pytest.fixture(scope="module")
def reference_math(deployer):
    with boa.env.prank(deployer):
        return boa.load_partial(REFERENCE_MATH).deploy()


def _outcome(fn, *args):
    try:
        return fn(*args)
    except boa.BoaError:
        return "revert"


def _log_uniform(rng, lo, hi):
    value = int(10 ** rng.uniform(pymath.log10(lo), pymath.log10(hi)))
    # the float drops the low digits; fill them in
    value += rng.randrange(max(value // 10**9, 1))
    return min(max(value, lo), hi)


def _draw_A(rng):
    roll = rng.random()
    if roll < 0.05:
        return rng.choice([MIN_A - 1, MAX_A + 1])  # outside the math's domain
    if roll < 0.20:
        return rng.choice([MIN_A, MIN_A + 1, MAX_A - 1, MAX_A])
    return _log_uniform(rng, MIN_A, MAX_A)


def _draw_gamma(rng):
    roll = rng.random()
    if roll < 0.05:
        return rng.choice([MIN_GAMMA - 1, MAX_GAMMA + 1])
    if roll < 0.30:
        return rng.choice(GAMMA_EDGES)
    return _log_uniform(rng, MIN_GAMMA, MAX_GAMMA)


def _draw_D(rng):
    roll = rng.random()
    if roll < 0.05:
        return rng.choice([MIN_D - 1, MIN_D, MAX_D, MAX_D + 1])
    return _log_uniform(rng, MIN_D, MAX_D)


def _draw_fraction(rng):
    """x / D in 1e18 precision; mostly near balance, sometimes far outside the domain."""
    if rng.random() < 0.75:
        return _log_uniform(rng, 5 * 10**16, 5 * 10**18)
    return _log_uniform(rng, 10**14, 10**20)


@pytest.mark.parametrize("chunk", range(N_CHUNKS))
def test_solvers_match_reference(math_contract, reference_math, chunk):
    rng = random.Random(f"twocrypto-math-parity-{chunk}")
    solved = 0

    for _ in range(CASES_PER_CHUNK):
        A = _draw_A(rng)
        gamma = _draw_gamma(rng)
        D = _draw_D(rng)
        x = [D * _draw_fraction(rng) // 10**18, D * _draw_fraction(rng) // 10**18]
        i = rng.randrange(2)
        case = dict(A=A, gamma=gamma, x=x, D=D, i=i)

        expected = _outcome(reference_math.get_y, A, gamma, x, D, i)
        assert _outcome(math_contract.get_y, A, gamma, x, D, i) == expected, case
        if expected != "revert":
            solved += 1

        expected_newton_y = _outcome(reference_math.newton_y, A, gamma, x, D, i)
        assert _outcome(math_contract.newton_y, A, gamma, x, D, i) == expected_newton_y, case

        hints = [0]
        if expected != "revert" and expected[1] > 0:
            hints.append(expected[1])
        for K0_prev in hints:
            expected_D = _outcome(reference_math.newton_D, A, gamma, x, K0_prev)
            assert _outcome(math_contract.newton_D, A, gamma, x, K0_prev) == expected_D, (
                case,
                K0_prev,
            )

        D_x = _outcome(reference_math.newton_D, A, gamma, x, 0)
        if D_x == "revert":
            D_x = D
        expected_p = _outcome(reference_math.get_p, x, D_x, [A, gamma])
        assert _outcome(math_contract.get_p, x, D_x, [A, gamma]) == expected_p, (case, D_x)

    # at least a third of the draws must solve, or the comparison says little
    assert solved >= CASES_PER_CHUNK // 3


DIVIDERS = [
    (10**48, 10**30),
    (10**46, 10**28),
    (10**44, 10**26),
    (10**42, 10**24),
    (10**40, 10**22),
    (10**38, 10**20),
    (10**36, 10**18),
    (10**34, 10**16),
    (10**32, 10**14),
    (10**30, 10**12),
    (10**28, 10**10),
    (10**26, 10**8),
    (10**24, 10**6),
    (10**20, 10**2),
]


def _sdiv(a, b):
    """Signed integer division truncating toward zero, as Vyper and the EVM do."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def _cube_root_signs(ANN, gamma, x, D, i):
    """
    Signs of b and delta1 as get_y computes them. They select which of the
    four cube-root calls run on the analytic path (b > 0 or not for b_cbrt,
    delta1 > 0 or not for second_cbrt).
    """
    x_j = x[1 - i]
    gamma2 = gamma * gamma
    ann_gamma2 = ANN * gamma2
    a = 10**32
    b = D * ann_gamma2 // 400000000 // x_j - 3 * 10**32 - 2 * gamma * 10**14
    c = (
        3 * 10**32
        + 4 * gamma * 10**14
        + gamma2 // 10**4
        + (4 * ann_gamma2 // 400000000) * x_j // D
        - 4 * ann_gamma2 // 400000000
    )
    d = -((10**18 + gamma) ** 2 // 10**4)
    delta0 = _sdiv(3 * a * c, b) - b
    delta1 = 3 * delta0 + b - _sdiv(_sdiv(27 * a**2, b) * d, b)
    threshold = min(abs(delta0), abs(delta1), a)
    divider = next((value for limit, value in DIVIDERS if threshold > limit), 1)
    a, b, c, d = (_sdiv(v, divider) for v in (a, b, c, d))
    delta0 = _sdiv(3 * a * c, b) - b
    delta1 = 3 * delta0 + b - _sdiv(_sdiv(27 * a**2, b) * d, b)
    return b > 0, delta1 > 0


def test_every_get_y_path_matches_reference(math_contract, reference_math):
    """
    Draws seeded ordinary inputs until each cube-root call in get_y and the
    newton_y fallback has produced successful results, each one compared with
    the reference. Random sampling alone reaches some paths rarely (b > 0 in
    about 1 of 300 ordinary draws).
    """
    rng = random.Random("twocrypto-math-parity-paths")
    needed = {"b > 0": 3, "b <= 0": 3, "delta1 > 0": 3, "delta1 <= 0": 3, "fallback": 3}

    for _ in range(6000):
        if not any(needed.values()):
            break
        A = _log_uniform(rng, MIN_A, MAX_A)
        gamma = _log_uniform(rng, MIN_GAMMA, MAX_GAMMA)
        D = _log_uniform(rng, MIN_D, MAX_D)
        x = [D * _log_uniform(rng, 5 * 10**16, 5 * 10**18) // 10**18 for _ in range(2)]
        i = rng.randrange(2)

        expected = _outcome(reference_math.get_y, A, gamma, x, D, i)
        if expected == "revert":
            continue
        if expected[1] == 0:
            paths = ["fallback"]
        else:
            b_positive, delta1_positive = _cube_root_signs(A, gamma, x, D, i)
            paths = [
                "b > 0" if b_positive else "b <= 0",
                "delta1 > 0" if delta1_positive else "delta1 <= 0",
            ]
        if not any(needed[path] for path in paths):
            continue

        assert math_contract.get_y(A, gamma, x, D, i) == expected, dict(
            A=A, gamma=gamma, x=x, D=D, i=i
        )
        for path in paths:
            needed[path] = max(needed[path] - 1, 0)

    assert not any(needed.values()), needed


@pytest.mark.parametrize("offset, solves", [(0, False), (1, False), (10**11, False), (10**13, True)])
def test_get_y_reverts_near_b_zero_like_reference(math_contract, reference_math, offset, solves):
    # Known and kept: near b == 0 (exactly at x_j == 110e18 here) the analytic
    # get_y divides by zero or overflows and reverts, as in the reference.
    A, gamma, D = 7_040_000, 10**17, 200 * 10**18
    for sign in (1, -1):
        x = [110 * 10**18 + sign * offset, 100 * 10**18]
        expected = _outcome(reference_math.get_y, A, gamma, x, D, 1)
        assert (expected != "revert") == solves
        assert _outcome(math_contract.get_y, A, gamma, x, D, 1) == expected


def test_wad_exp_matches_reference(math_contract, reference_math):
    rng = random.Random("twocrypto-math-parity-wad-exp")
    gap = (WAD_EXP_ZERO_CUTOFF_REFERENCE, WAD_EXP_ZERO_CUTOFF_SNEKMATE)
    points = [
        -(2**255),
        WAD_EXP_ZERO_CUTOFF_REFERENCE - 1,
        WAD_EXP_ZERO_CUTOFF_REFERENCE,
        WAD_EXP_ZERO_CUTOFF_REFERENCE + 1,
        WAD_EXP_ZERO_CUTOFF_SNEKMATE - 1,
        WAD_EXP_ZERO_CUTOFF_SNEKMATE,
        WAD_EXP_ZERO_CUTOFF_SNEKMATE + 1,
        -(10**18),
        -1,
        0,
        1,
        10**18,
        WAD_EXP_OVERFLOW - 1,
        WAD_EXP_OVERFLOW,
        WAD_EXP_OVERFLOW + 1,
        2**255 - 1,
    ]
    # the interval where the two sources take different early-zero shortcuts
    points += [rng.randint(gap[0] + 1, gap[1]) for _ in range(300)]
    # the oracle's working range: exp(-elapsed / ma_time) for any elapsed time
    points += [rng.randint(-50 * 10**18, 0) for _ in range(150)]
    points += [rng.randint(0, WAD_EXP_OVERFLOW - 1) for _ in range(50)]

    for x in points:
        expected = _outcome(reference_math.wad_exp, x)
        actual = _outcome(math_contract.wad_exp, x)
        if expected == "revert":
            assert actual == "revert", x
        else:
            assert expected >= 0, x
            assert actual == expected, x
