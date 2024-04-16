import boa
import pytest
from hypothesis import event, given, settings
from hypothesis import strategies as st

N_COINS = 2
# MAX_SAMPLES = 1000000  # Increase for fuzzing
MAX_SAMPLES = 10000
N_CASES = 32

A_MUL = 10000
MIN_A = int(N_COINS**N_COINS * A_MUL / 10)
MAX_A = int(N_COINS**N_COINS * A_MUL * 1000)

# Old bounds for gamma
# should be used only when comparing convergence with the old version
MIN_GAMMA_CMP = 10**10
MAX_GAMMA_CMP = 2 * 10**15


@pytest.fixture(scope="module")
def math_large_gamma():
    return boa.load("contracts/mocks/newton_y_large_gamma.vy")


@pytest.fixture(scope="module")
def math_small_gamma():
    return boa.load("contracts/mocks/newton_y_small_gamma.vy")


@given(
    A=st.integers(min_value=MIN_A, max_value=MAX_A),
    D=st.integers(
        min_value=10**18, max_value=10**14 * 10**18
    ),  # 1 USD to 100T USD
    xD=st.integers(
        min_value=10**17 // 2, max_value=10**19 // 2
    ),  # <- ratio 1e18 * x/D, typically 1e18 * 1
    yD=st.integers(
        min_value=10**17 // 2, max_value=10**19 // 2
    ),  # <- ratio 1e18 * y/D, typically 1e18 * 1
    gamma=st.integers(min_value=MIN_GAMMA_CMP, max_value=MAX_GAMMA_CMP),
    j=st.integers(min_value=0, max_value=1),
)
@settings(max_examples=MAX_SAMPLES, deadline=None)
def test_newton_y_equivalence(
    math_small_gamma, math_large_gamma, A, D, xD, yD, gamma, j
):
    """
    Tests whether the newton_y function converges to the same
    value for both the old and new versions
    """
    X = [D * xD // 10**18, D * yD // 10**18]
    y_small, iterations_old = math_small_gamma.newton_y(A, gamma, X, D, j)
    y_large, iterations_new = math_large_gamma.newton_y(A, gamma, X, D, j)

    # print(math_large_gamma.internal._newton_y)

    event(f"converges in {iterations_new} iterations")

    # create events depending on the differences between iterations
    assert iterations_old - iterations_new == 0
    assert y_small == y_large
