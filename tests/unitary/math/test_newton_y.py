import boa
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

N_COINS = 2
# MAX_SAMPLES = 1000000  # Increase for fuzzing
MAX_SAMPLES = 10000
N_CASES = 32

A_MUL = 10000
MIN_A = int(N_COINS**N_COINS * A_MUL / 10)
MAX_A = int(N_COINS**N_COINS * A_MUL * 1000)

MIN_GAMMA = 10**10
MAX_GAMMA = 3 * 10**17


@pytest.fixture(scope="module")
def math_large_gamma():
    return boa.load("contracts/mocks/newton_y_large_gamma.vy")


@pytest.fixture(scope="module")
def math_small_gamma():
    return boa.load("contracts/mock/newton_y_small_gamma.vy")


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
    gamma=st.integers(min_value=MIN_GAMMA, max_value=MAX_GAMMA),
    j=st.integers(min_value=0, max_value=1),
)
@settings(max_examples=MAX_SAMPLES, deadline=None)
def test_iteration_diff(math_large_gamma, A, D, xD, yD, gamma, j):
    pass
    # TODO: make a test that:
    # - measures how many iterations it takes for the
    #   old value to converge between the two versions
    # - makes sure that we're converging to the correct value
    # - use hypothesis.note to have some clear statistics about
    #   the differences in divergence
    # X = [D * xD // 10**18, D * yD // 10**18]
    # math_large_gamma.newton_y(A, gamma, X, D, j)
