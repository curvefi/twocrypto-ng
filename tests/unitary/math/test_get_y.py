# flake8: noqa
import time
from decimal import Decimal

import boa
import pytest
from hypothesis import event, given, note, settings
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

pytest.current_case_id = 0
pytest.negative_sqrt_arg = 0
pytest.gas_original = 0
pytest.gas_new = 0
pytest.t_start = time.time()


def inv_target_decimal_n2(A, gamma, x, D):
    N = len(x)

    x_prod = Decimal(1)
    for x_i in x:
        x_prod *= x_i
    K0 = x_prod / (Decimal(D) / N) ** N
    K0 *= 10**18

    if gamma > 0:
        # K = gamma**2 * K0 / (gamma + 10**18*(Decimal(1) - K0))**2
        K = gamma**2 * K0 / (gamma + 10**18 - K0) ** 2 / 10**18
    K *= A

    f = (
        K * D ** (N - 1) * sum(x)
        + x_prod
        - (K * D**N + (Decimal(D) / N) ** N)
    )

    return f


def test_get_y_revert(math_contract):
    a = 1723894848
    gamma = 24009999997600
    x = [112497148627520223862735198942112, 112327102289152450435452075003508]
    D = 224824250915890636214130540882688
    i = 0

    with boa.reverts():
        math_contract.newton_y(a, gamma, x, D, i)

    with boa.reverts():
        math_contract.get_y(a, gamma, x, D, i)


@pytest.mark.parametrize(
    "_tmp", range(N_CASES)
)  # Parallelisation hack (more details in folder's README)
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
def test_get_y(math_unoptimized, math_optimized, A, D, xD, yD, gamma, j, _tmp):
    pytest.current_case_id += 1
    X = [D * xD // 10**18, D * yD // 10**18]

    A_dec = Decimal(A) / 10000 / 4

    def calculate_F_by_y0(y0):
        new_X = X[:]
        new_X[j] = y0
        return inv_target_decimal_n2(A_dec, gamma, new_X, D)

    try:
        result_original = math_unoptimized.newton_y(A, gamma, X, D, j)
    except Exception as e:
        if "unsafe value" in str(e):
            assert not "gamma" in str(e)
            assert gamma > 2 * 10**16
            return
        else:  # Did not converge?
            raise
    pytest.gas_original += math_unoptimized._computation.get_gas_used()

    try:
        result_get_y, K0 = math_optimized.get_y(A, gamma, X, D, j)
    except Exception as e:
        if "unsafe value" in str(e):
            # The only possibility for old one to not revert and new one to revert is to have
            # very small difference near the unsafe y value boundary.
            # So, here we check if it was indeed small
            lim_mul = 100 * 10**18
            if gamma > 2 * 10**16:
                lim_mul = lim_mul * 2 * 10**16 // gamma
            frac = result_original * 10**18 // D
            if (
                abs(frac - 10**36 // 2 // lim_mul) < 100
                or abs(frac - lim_mul // 2) < 100
            ):
                return
            else:
                raise
        else:
            raise
    pytest.gas_new += math_optimized._computation.get_gas_used()

    note(
        "{"
        f"'ANN': {A}, 'GAMMA': {gamma}, 'x': {X}, 'D': {D}, 'index': {j}"
        "}\n"
    )

    if K0 == 0:
        event("fallback to newton_y")
        pytest.negative_sqrt_arg += 1
        return

    if pytest.current_case_id % 1000 == 0:
        print(
            f"--- {pytest.current_case_id}\nPositive dy frac: {100*pytest.negative_sqrt_arg/pytest.current_case_id:.1f}%\t{time.time() - pytest.t_start:.1f} seconds.\n"
            f"Gas advantage per call: {pytest.gas_original//pytest.current_case_id} {pytest.gas_new//pytest.current_case_id}\n"
        )

    assert abs(result_original - result_get_y) <= max(
        10**4, result_original / 1e8
    ) or abs(calculate_F_by_y0(result_get_y)) <= abs(
        calculate_F_by_y0(result_original)
    )
