import copy

import boa

from tests.utils.constants import UNIX_DAY


def test_ramp_A_gamma_up(swap, factory_admin, params):

    p = copy.deepcopy(params)
    future_A = p["A"] + 10000
    future_gamma = p["gamma"] + 10000
    future_time = boa.env.evm.patch.timestamp + UNIX_DAY

    initial_A_gamma = [swap.A(), swap.gamma()]
    swap.ramp_A_gamma(
        future_A, future_gamma, future_time, sender=factory_admin
    )

    boa.env.time_travel(10000)
    current_A_gamma = [swap.A(), swap.gamma()]
    for i in range(2):
        assert current_A_gamma[i] > initial_A_gamma[i]

    boa.env.time_travel(76400)
    current_A_gamma = [swap.A(), swap.gamma()]
    assert current_A_gamma[0] == future_A
    assert current_A_gamma[1] == future_gamma


def test_ramp_A_gamma_down(swap, factory_admin, params):

    p = copy.deepcopy(params)
    future_A = p["A"] - 10000
    future_gamma = p["gamma"] - 10000
    future_time = boa.env.evm.patch.timestamp + UNIX_DAY

    initial_A_gamma = [swap.A(), swap.gamma()]
    swap.ramp_A_gamma(
        future_A, future_gamma, future_time, sender=factory_admin
    )

    boa.env.time_travel(10000)
    current_A_gamma = [swap.A(), swap.gamma()]
    for i in range(2):
        assert current_A_gamma[i] < initial_A_gamma[i]

    boa.env.time_travel(76400)
    current_A_gamma = [swap.A(), swap.gamma()]
    assert current_A_gamma[0] == future_A
    assert current_A_gamma[1] == future_gamma
