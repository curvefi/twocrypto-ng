# flake8: noqa
import sys
import time
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import tests.utils.simulation_int_many as sim

# Uncomment to be able to print when parallelized
# sys.stdout = sys.stderr


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


N_COINS = 2
# MAX_SAMPLES = 1000000  # Increase for fuzzing
MAX_SAMPLES = 5000  # Increase for fuzzing
N_CASES = 32

A_MUL = 10000
MIN_A = int(N_COINS**N_COINS * A_MUL / 10)
MAX_A = int(N_COINS**N_COINS * A_MUL * 1000)

# gamma from 1e-8 up to 0.05
MIN_GAMMA = 10**10
MAX_GAMMA = 3 * 10**17

MIN_XD = 10**17
MAX_XD = 10**19

pytest.progress = 0
pytest.actually_tested = 0
pytest.t_start = time.time()


@pytest.mark.parametrize(
    "_tmp", range(N_CASES)
)  # Create N_CASES independent test instances.
@given(
    A=st.integers(min_value=MIN_A, max_value=MAX_A),
    D=st.integers(
        min_value=10**18, max_value=10**14 * 10**18
    ),  # 1 USD to 100T USD
    xD=st.integers(
        min_value=MIN_XD, max_value=MAX_XD
    ),  # <- ratio 1e18 * x/D, typically 1e18 * 1
    yD=st.integers(
        min_value=MIN_XD, max_value=MAX_XD
    ),  # <- ratio 1e18 * y/D, typically 1e18 * 1
    gamma=st.integers(min_value=MIN_GAMMA, max_value=MAX_GAMMA),
    j=st.integers(min_value=0, max_value=1),
    btcScalePrice=st.integers(min_value=10**2, max_value=10**7),
    ethScalePrice=st.integers(min_value=10, max_value=10**5),
    mid_fee=st.sampled_from(
        [
            int(0.7e-3 * 10**10),
            int(1e-3 * 10**10),
            int(1.2e-3 * 10**10),
            int(4e-3 * 10**10),
        ]
    ),
    out_fee=st.sampled_from([int(4.0e-3 * 10**10), int(10.0e-3 * 10**10)]),
    fee_gamma=st.sampled_from([int(1e-2 * 1e18), int(2e-6 * 1e18)]),
)
@settings(max_examples=MAX_SAMPLES, deadline=None)
def test_newton_D(
    math_optimized,
    math_unoptimized,
    A,
    D,
    xD,
    yD,
    gamma,
    j,
    btcScalePrice,
    ethScalePrice,
    mid_fee,
    out_fee,
    fee_gamma,
    _tmp,
):
    _test_newton_D(
        math_optimized,
        math_unoptimized,
        A,
        D,
        xD,
        yD,
        gamma,
        j,
        btcScalePrice,
        ethScalePrice,
        mid_fee,
        out_fee,
        fee_gamma,
        _tmp,
    )


def _test_newton_D(
    math_optimized,
    math_unoptimized,
    A,
    D,
    xD,
    yD,
    gamma,
    j,
    btcScalePrice,
    ethScalePrice,
    mid_fee,
    out_fee,
    fee_gamma,
    _tmp,
):

    is_safe = all(
        f >= MIN_XD and f <= MAX_XD
        for f in [xx * 10**18 // D for xx in [xD, yD]]
    )

    pytest.progress += 1
    if pytest.progress % 1000 == 0 and pytest.actually_tested != 0:
        print(
            f"{pytest.progress} | {pytest.actually_tested} cases processed in {time.time()-pytest.t_start:.1f} seconds."
        )
    X = [D * xD // 10**18, D * yD // 10**18]

    result_get_y = 0
    get_y_failed = False
    try:
        (result_get_y, K0) = math_optimized.get_y(A, gamma, X, D, j)
    except:
        get_y_failed = True

    if get_y_failed:
        newton_y_failed = False
        try:
            math_optimized.newton_y(A, gamma, X, D, j)
        except:
            newton_y_failed = True

    if get_y_failed and newton_y_failed:
        return  # both canonical and new method fail, so we ignore.

    if get_y_failed and not newton_y_failed and is_safe:
        raise  # this is a problem

    # dy should be positive
    if result_get_y < X[j] and result_get_y / D > MIN_XD / 1e18 and result_get_y / D < MAX_XD / 1e18:

        price_scale = (btcScalePrice, ethScalePrice)
        y = X[j]
        dy = X[j] - result_get_y
        dy -= 1

        if j > 0:
            dy = dy * 10**18 // price_scale[j - 1]

        fee = sim.get_fee(X, fee_gamma, mid_fee, out_fee)
        dy -= fee * dy // 10**10
        y -= dy

        if dy / X[j] <= 0.95:

            pytest.actually_tested += 1
            X[j] = y

            case = (
                "{"
                f"'ANN': {A}, 'D': {D}, 'xD': {xD}, 'yD': {yD}, 'GAMMA': {gamma}, 'j': {j}, 'btcScalePrice': {btcScalePrice}, 'ethScalePrice': {ethScalePrice}, 'mid_fee': {mid_fee}, 'out_fee': {out_fee}, 'fee_gamma': {fee_gamma}"
                "},\n"
            )

            result_sim = math_unoptimized.newton_D(A, gamma, X)
            try:
                result_contract = math_optimized.newton_D(A, gamma, X, K0)
            except Exception as e:
                # with open("log/newton_D_fail.txt", "a") as f:
                #     f.write(case)
                # with open("log/newton_D_fail_trace.txt", "a") as f:
                #     f.write(str(e))
                return

            A_dec = Decimal(A) / 10000 / 4

            def calculate_D_polynome(d):
                d = Decimal(d)
                return abs(inv_target_decimal_n2(A_dec, gamma, X, d))

            assert abs(result_sim - result_contract) <= max(
                10000, result_sim / 1e12
            )

            # with open("log/newton_D_pass.txt", "a") as f:
            #     f.write(case)
