import pytest
from hypothesis import event, given, note, settings
from hypothesis import strategies as st

import tests.utils.simulator as sim
from tests.utils.strategies import A, fee_gamma, fees, gamma

# you might want to increase this when fuzzing locally
MAX_SAMPLES = 10000
N_CASES = 32

MIN_XD = 10**17
MAX_XD = 10**19


@pytest.mark.parametrize(
    "_tmp", range(N_CASES)
)  # Parallelisation hack (more details in folder's README)
@given(
    D=st.integers(
        min_value=10**18, max_value=10**14 * 10**18
    ),  # 1 USD to 100T USD
    xD=st.integers(
        min_value=MIN_XD, max_value=MAX_XD
    ),  # ratio 1e18 * x/D, typically 1e18 * 1
    yD=st.integers(
        min_value=MIN_XD, max_value=MAX_XD
    ),  # ratio 1e18 * y/D, typically 1e18 * 1
    j=st.integers(min_value=0, max_value=1),
    btcScalePrice=st.integers(min_value=10**2, max_value=10**7),
    ethScalePrice=st.integers(min_value=10, max_value=10**5),
    A=A,
    gamma=gamma,
    mid_out_fee=fees(),
    fee_gamma=fee_gamma,
)
@settings(max_examples=MAX_SAMPLES, deadline=None)
def test_newton_D(
    math_optimized,
    math_unoptimized,
    D,
    xD,
    yD,
    A,
    gamma,
    j,
    btcScalePrice,
    ethScalePrice,
    mid_out_fee,
    fee_gamma,
    _tmp,
):

    is_safe = all(
        f >= MIN_XD and f <= MAX_XD
        for f in [xx * 10**18 // D for xx in [xD, yD]]
    )

    X = [D * xD // 10**18, D * yD // 10**18]

    result_get_y = 0
    get_y_failed = False
    try:
        (result_get_y, K0) = math_optimized.get_y(A, gamma, X, D, j)
    except Exception:
        get_y_failed = True

    if get_y_failed:
        newton_y_failed = False
        try:
            math_optimized.newton_y(A, gamma, X, D, j)
        except Exception:
            newton_y_failed = True

    if get_y_failed and newton_y_failed:
        return  # both canonical and new method fail, so we ignore.

    if get_y_failed and not newton_y_failed and is_safe:
        raise  # this is a problem

    # dy should be positive
    if (
        result_get_y < X[j]
        and result_get_y / D > MIN_XD / 1e18
        and result_get_y / D < MAX_XD / 1e18
    ):

        price_scale = (btcScalePrice, ethScalePrice)
        y = X[j]
        dy = X[j] - result_get_y
        dy -= 1

        if j > 0:
            dy = dy * 10**18 // price_scale[j - 1]

        fee = sim.get_fee(X, fee_gamma, mid_out_fee[0], mid_out_fee[1])
        dy -= fee * dy // 10**10
        y -= dy

        if dy / X[j] <= 0.95:

            # if we stop before this block we are not testing newton_D
            event("test actually went through")
            X[j] = y

            note(
                ", A: {:.2e}".format(A)
                + ", D: {:.2e}".format(D)
                + ", xD: {:.2e}".format(xD)
                + ", yD: {:.2e}".format(yD)
                + ", GAMMA: {:.2e}".format(gamma)
                + ", j: {:.2e}".format(j)
                + ", btcScalePrice: {:.2e}".format(btcScalePrice)
                + ", ethScalePrice: {:.2e}".format(ethScalePrice)
                + ", mid_fee: {:.2e}".format(mid_out_fee[0])
                + ", out_fee: {:.2e}".format(mid_out_fee[1])
                + ", fee_gamma: {:.2e}".format(fee_gamma)
            )

            result_sim = math_unoptimized.newton_D(A, gamma, X)
            result_contract = math_optimized.newton_D(A, gamma, X, K0)

            assert abs(result_sim - result_contract) <= max(
                10000, result_sim / 1e12
            )
