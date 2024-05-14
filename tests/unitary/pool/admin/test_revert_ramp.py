import boa

from tests.utils.constants import UNIX_DAY


def test_revert_unauthorised_ramp(swap, user):

    with boa.env.prank(user), boa.reverts(dev="only owner"):
        swap.ramp_A_gamma(1, 1, 1)


def test_revert_ramp_while_ramping(swap, factory_admin):

    # sanity check: ramping is not active
    assert swap.initial_A_gamma_time() == 0

    A_gamma = [swap.A(), swap.gamma()]
    future_time = boa.env.evm.patch.timestamp + UNIX_DAY + 1
    with boa.env.prank(factory_admin):
        swap.ramp_A_gamma(A_gamma[0] + 1, A_gamma[1] + 1, future_time)

        with boa.reverts(dev="ramp undergoing"):
            swap.ramp_A_gamma(A_gamma[0], A_gamma[1], future_time)


def test_revert_fast_ramps(swap, factory_admin):

    A_gamma = [swap.A(), swap.gamma()]
    future_time = boa.env.evm.patch.timestamp + 10
    with boa.env.prank(factory_admin), boa.reverts(dev="insufficient time"):
        swap.ramp_A_gamma(A_gamma[0] + 1, A_gamma[1] + 1, future_time)


def test_revert_unauthorised_stop_ramp(swap, factory_admin, user):

    # sanity check: ramping is not active
    assert swap.initial_A_gamma_time() == 0

    A_gamma = [swap.A(), swap.gamma()]
    future_time = boa.env.evm.patch.timestamp + UNIX_DAY + 1
    with boa.env.prank(factory_admin):
        swap.ramp_A_gamma(A_gamma[0] + 1, A_gamma[1] + 1, future_time)

    with boa.env.prank(user), boa.reverts(dev="only owner"):
        swap.stop_ramp_A_gamma()


def test_revert_ramp_too_far(swap, factory_admin):

    # sanity check: ramping is not active
    assert swap.initial_A_gamma_time() == 0

    A = swap.A()
    gamma = swap.gamma()
    future_time = boa.env.evm.patch.timestamp + UNIX_DAY + 1

    with boa.env.prank(factory_admin), boa.reverts(dev="A change too high"):
        future_A = A * 11  # can at most increase by 10x
        swap.ramp_A_gamma(future_A, gamma, future_time)
    with boa.env.prank(factory_admin), boa.reverts(dev="A change too low"):
        future_A = A // 11  # can at most decrease by 10x
        swap.ramp_A_gamma(future_A, gamma, future_time)

    with boa.env.prank(factory_admin), boa.reverts(
        dev="gamma change too high"
    ):
        future_gamma = gamma * 11  # can at most increase by 10x
        swap.ramp_A_gamma(A, future_gamma, future_time)
    with boa.env.prank(factory_admin), boa.reverts(dev="gamma change too low"):
        future_gamma = gamma // 11  # can at most decrease by 10x
        swap.ramp_A_gamma(A, future_gamma, future_time)
