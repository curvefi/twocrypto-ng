from decimal import Decimal

import boa
import pytest
from hypothesis import event, given, note, settings
from hypothesis.strategies import integers

from tests.utils.strategies import A, gamma

# you might want to increase this when fuzzing locally
MAX_SAMPLES = 10000
# N_CASES = 32 # Increase for fuzzing
N_CASES = 1


def inv_target_decimal_n2(A, gamma, x, D):
    """Computes the inavriant (F) as described
    in the whitepaper.
    """
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

    f = K * D ** (N - 1) * sum(x) + x_prod - (K * D**N + (Decimal(D) / N) ** N)

    return f


def test_get_y_revert(math_contract):
    a = 1723894848
    gamma = 24009999997600
    x = [112497148627520223862735198942112, 112327102289152450435452075003508]
    D = 224824250915890636214130540882688
    i = 0

    with boa.reverts(dev="unsafe values A"):
        math_contract.newton_y(a, gamma, x, D, i)

    with boa.reverts(dev="unsafe values A"):
        math_contract.get_y(a, gamma, x, D, i)


@pytest.mark.parametrize(
    "_tmp", range(N_CASES)
)  # Parallelisation hack (more details in folder's README)
@given(
    A=A,
    gamma=gamma,
    D=integers(min_value=10**18, max_value=10**14 * 10**18),  # 1 USD to 100T USD
    xD=integers(
        min_value=10**17 // 2, max_value=10**19 // 2
    ),  # ratio 1e18 * x/D, typically 1e18 * 1
    yD=integers(
        min_value=10**17 // 2, max_value=10**19 // 2
    ),  # ratio 1e18 * y/D, typically 1e18 * 1
    j=integers(min_value=0, max_value=1),
)
@settings(max_examples=MAX_SAMPLES, deadline=None)
def test_get_y(math_unoptimized, math_optimized, A, D, xD, yD, gamma, j, _tmp):
    # pytest.current_case_id += 1
    X = [D * xD // 10**18, D * yD // 10**18]

    A_dec = Decimal(A) / 10000 / 4

    def calculate_F_by_y0(y0):
        new_X = X[:]
        new_X[j] = y0
        return inv_target_decimal_n2(A_dec, gamma, new_X, D)

    try:
        result_original = math_unoptimized.newton_y(A, gamma, X, D, j)
    except Exception as e:
        event("hit unsafe for unoptimizied")
        if "unsafe value" in str(e):
            assert "unsafe value for gamma" not in str(e)
            assert gamma > 2 * 10**16
            return
        else:  # Did not converge?
            raise
    unoptimized_gas = math_unoptimized._computation.net_gas_used
    event("unoptimizied implementation used {:.0e} gas".format(unoptimized_gas))

    try:
        result_get_y, K0 = math_optimized.get_y(A, gamma, X, D, j)
    except Exception as e:
        event("hit unsafe for optimizied")
        if "unsafe value" in str(e):
            # The only possibility for old one to not revert and
            # new one to revert is to have very small difference
            # near the unsafe y value boundary.
            # So, here we check if it was indeed small
            lim_mul = 100 * 10**18
            if gamma > 2 * 10**16:
                lim_mul = lim_mul * 2 * 10**16 // gamma
            frac = result_original * 10**18 // D
            if abs(frac - 10**36 // 2 // lim_mul) < 100 or abs(frac - lim_mul // 2) < 100:
                return
            else:
                raise
        else:
            raise
    optimized_gas = math_optimized._computation.net_gas_used
    event("optimizied implementation used {:.0e} gas".format(optimized_gas))

    note("{" f"'ANN': {A}, 'GAMMA': {gamma}, 'x': {X}, 'D': {D}, 'index': {j}" "}\n")

    if K0 == 0:
        event("fallback to newton_y")
        return

    assert abs(result_original - result_get_y) <= max(10**4, result_original / 1e8) or abs(
        calculate_F_by_y0(result_get_y)
    ) <= abs(calculate_F_by_y0(result_original))
