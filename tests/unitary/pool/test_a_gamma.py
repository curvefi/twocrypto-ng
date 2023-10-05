import boa


def test_A_gamma(swap, params):

    A = swap.A()
    gamma = swap.gamma()

    assert A == params["A"]
    assert gamma == params["gamma"]


def test_revert_ramp_A_gamma(swap, factory_admin):

    A = swap.A()
    gamma = swap.gamma()
    future_A = A * 10  # 10 is too large of a jump
    future_gamma = gamma // 100
    t0 = boa.env.vm.state.timestamp
    t1 = t0 + 7 * 86400

    with boa.env.prank(factory_admin), boa.reverts():
        swap.ramp_A_gamma(future_A, future_gamma, t1)


# https://github.com/curvefi/curve-factory-crypto/blob/master/tests/test_a_gamma.py
def test_ramp_A_gamma(swap, factory_admin):

    A = swap.A()
    gamma = swap.gamma()
    A_gamma_initial = [A, gamma]

    future_A = A * 9
    future_gamma = gamma // 10
    t0 = boa.env.vm.state.timestamp
    t1 = t0 + 7 * 86400

    with boa.env.prank(factory_admin):
        swap.ramp_A_gamma(future_A, future_gamma, t1)

    for i in range(1, 8):
        boa.env.time_travel(86400)
        A_gamma = [swap.A(), swap.gamma()]
        assert (
            abs(
                A_gamma[0]
                - (
                    A_gamma_initial[0]
                    + (future_A - A_gamma_initial[0]) * i / 7
                )
            )
            < 1e-4 * A_gamma_initial[0]
        )
        assert (
            abs(
                A_gamma[1]
                - (
                    A_gamma_initial[1]
                    + (future_gamma - A_gamma_initial[1]) * i / 7
                )
            )
            < 1e-4 * A_gamma_initial[1]
        )
