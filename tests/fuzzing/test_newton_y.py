"""
This test suite was added as part of PR #12 to verify
the correctness of the newton_y function in the math
contract.

Since the introduction of `get_y` this function is just used
as a fallback when the analytical method fails to find a solution
for y (roughly 3% of the time).

Since bounds for gamma have been not only restored to the original
tricrypto levels but even pushed forward this suite aims to
test the convergence of the newton_y function in the new bounds.

Since calls to newton_y are not that frequent anymore this test suite
tries to test it in isolation.

While the tests are quite similar, they have been separated to obtain
more fine-grained information about the convergence of the newton_y
through hypothesis events.

We don't test the correctness of y because newton_y should always
converge to the correct value (or not converge at all otherwise).
"""

import pytest
from hypothesis import event, given, settings
from hypothesis import strategies as st

from tests.utils.constants import MAX_GAMMA, MAX_GAMMA_SMALL, MIN_GAMMA

N_COINS = 2
# MAX_SAMPLES = 1000000  # Increase for fuzzing
MAX_SAMPLES = 10000
N_CASES = 32
# for tests that are trivial
N_CASES_TRIVIAL = 6

A_MUL = 10000
MIN_A = int(N_COINS**N_COINS * A_MUL / 10)
MAX_A = int(N_COINS**N_COINS * A_MUL * 1000)

# Old bounds for gamma
MAX_GAMMA_OLD = 2 * 10**15


@pytest.fixture(scope="module")
def math_exposed():
    # compile
    from contracts import newton_y_exposed

    # deploy
    return newton_y_exposed()


@pytest.mark.parametrize(
    "_tmp", range(N_CASES_TRIVIAL)
)  # Parallelisation hack (more details in folder's README)
@given(
    A=st.integers(min_value=MIN_A, max_value=MAX_A),
    D=st.integers(min_value=10**18, max_value=10**14 * 10**18),  # 1 USD to 100T USD
    xD=st.integers(
        min_value=10**17 // 2, max_value=10**19 // 2
    ),  # <- ratio 1e18 * x/D, typically 1e18 * 1
    yD=st.integers(
        min_value=10**17 // 2, max_value=10**19 // 2
    ),  # <- ratio 1e18 * y/D, typically 1e18 * 1
    gamma=st.integers(min_value=MIN_GAMMA, max_value=MAX_GAMMA_OLD),
    j=st.integers(min_value=0, max_value=1),
)
@settings(max_examples=MAX_SAMPLES, deadline=None)
def test_equivalence(math_exposed, math_optimized, A, D, xD, yD, gamma, j, _tmp):
    """
    Tests whether the newton_y function works the same way
    for both the exposed and production versions on ranges that are
    already in production.

    [MIN_GAMMA, MAX_GAMMA_OLD] = [1e10, 2e15].
    """
    # using the same prices as in get_y fuzzing
    # TODO is this the correct way?
    X = [D * xD // 10**18, D * yD // 10**18]

    # this value remains as before the increase of the bounds
    # since we're testing the old bounds
    lim_mul = int(100e18)  # 100.0

    # we can use the old version to know the number of iterations
    # and the expected value
    y_exposed, iterations = math_exposed.internal._newton_y(A, gamma, X, D, j, lim_mul)

    # this should not revert (didn't converge or hit bounds)
    y = math_optimized.newton_y(A, gamma, X, D, j)

    event(f"converges in {iterations} iterations")

    assert y_exposed == y


@pytest.mark.parametrize(
    "_tmp", range(N_CASES_TRIVIAL)
)  # Parallelisation hack (more details in folder's README)
@given(
    A=st.integers(min_value=MIN_A, max_value=MAX_A),
    D=st.integers(min_value=10**18, max_value=10**14 * 10**18),  # 1 USD to 100T USD
    xD=st.integers(
        min_value=10**17 // 2, max_value=10**19 // 2
    ),  # <- ratio 1e18 * x/D, typically 1e18 * 1
    yD=st.integers(
        min_value=10**17 // 2, max_value=10**19 // 2
    ),  # <- ratio 1e18 * y/D, typically 1e18 * 1
    gamma=st.integers(min_value=MAX_GAMMA_OLD, max_value=MAX_GAMMA_SMALL),
    j=st.integers(min_value=0, max_value=1),
)
@settings(max_examples=MAX_SAMPLES, deadline=None)
def test_restored(math_optimized, math_exposed, A, D, xD, yD, gamma, j, _tmp):
    """
    Tests whether the bounds that have been restored to the original
    tricrypto ones work as expected.

    [MAX_GAMMA_OLD, MAX_GAMMA_SMALL] = [2e15, 2e16]
    """
    # using the same prices as in get_y fuzzing
    # TODO is this the correct way?
    X = [D * xD // 10**18, D * yD // 10**18]

    # according to vyper math contracts (get_y) since we never have
    # values bigger than MAX_GAMMA_SMALL, lim_mul is always 100
    lim_mul = int(100e18)  # 100.0

    # we can use the exposed version to know the number of iterations
    # and the expected value
    y_exposed, iterations = math_exposed.internal._newton_y(A, gamma, X, D, j, lim_mul)

    # this should not revert (didn't converge or hit bounds)
    y = math_optimized.internal._newton_y(A, gamma, X, D, j, lim_mul)

    # we can use the exposed version to know the number of iterations
    # since we didn't change how the computation is done
    event(f"converges in {iterations} iterations")

    assert y_exposed == y


@pytest.mark.parametrize(
    "_tmp", range(N_CASES)
)  # Parallelisation hack (more details in folder's README)
@given(
    A=st.integers(min_value=MIN_A, max_value=MAX_A),
    D=st.integers(min_value=10**18, max_value=10**14 * 10**18),  # 1 USD to 100T USD
    xD=st.integers(
        min_value=10**17 // 2, max_value=10**19 // 2
    ),  # <- ratio 1e18 * x/D, typically 1e18 * 1
    yD=st.integers(
        min_value=10**17 // 2, max_value=10**19 // 2
    ),  # <- ratio 1e18 * y/D, typically 1e18 * 1
    gamma=st.integers(min_value=MAX_GAMMA_SMALL + 1, max_value=MAX_GAMMA),
    j=st.integers(min_value=0, max_value=1),
)
@settings(max_examples=MAX_SAMPLES, deadline=None)
def test_new_bounds(math_optimized, math_exposed, A, D, xD, yD, gamma, j, _tmp):
    """
    Tests whether the new bouds that no pool has ever reached
    work as expected.

    [MAX_GAMMA_SMALL, MAX_GAMMA] = [2e16, 3e17]
    """
    # using the same prices as in get_y fuzzing
    # TODO is this the correct way?
    X = [D * xD // 10**18, D * yD // 10**18]

    # this comes from `get_y`` which is the only place from which _newton_y
    # is called when gamma is bigger than MAX_GAMMA_SMALL lim_mul has to
    # be adjusted accordingly
    lim_mul = 100e18 * MAX_GAMMA_SMALL // gamma  # smaller than 100.0

    y_exposed, iterations = math_exposed.internal._newton_y(A, gamma, X, D, j, int(lim_mul))

    # this should not revert (didn't converge or hit bounds)
    y = math_optimized.internal._newton_y(A, gamma, X, D, j, int(lim_mul))

    # we can use the exposed version to know the number of iterations
    # since we didn't change how the computation is done
    event(f"converges in {iterations} iterations")

    assert y == y_exposed
