import boa

from tests.utils.constants import UNIX_DAY


def test_revert_unauthorised_ramp(pool, user):
    with boa.env.prank(user), boa.reverts("only owner"):
        pool.ramp_A_gamma(1, 1, 1)


def test_revert_ramp_while_ramping(pool, factory_admin):
    # sanity check: ramping is not active
    assert pool.initial_A_gamma_time() == 0

    A_gamma = [pool.A(), pool.gamma()]
    future_time = boa.env.evm.patch.timestamp + UNIX_DAY + 1
    with boa.env.prank(factory_admin):
        pool.ramp_A_gamma(A_gamma[0] + 1, A_gamma[1] + 1, future_time)

        with boa.reverts("ramp undergoing"):
            pool.ramp_A_gamma(A_gamma[0], A_gamma[1], future_time)


def test_revert_fast_ramps(pool, factory_admin):
    A_gamma = [pool.A(), pool.gamma()]
    future_time = boa.env.evm.patch.timestamp + 10
    with boa.env.prank(factory_admin), boa.reverts("ramp time<min"):
        pool.ramp_A_gamma(A_gamma[0] + 1, A_gamma[1] + 1, future_time)


def test_revert_unauthorised_stop_ramp(pool, factory_admin, user):
    # sanity check: ramping is not active
    assert pool.initial_A_gamma_time() == 0

    A_gamma = [pool.A(), pool.gamma()]
    future_time = boa.env.evm.patch.timestamp + UNIX_DAY + 1
    with boa.env.prank(factory_admin):
        pool.ramp_A_gamma(A_gamma[0] + 1, A_gamma[1] + 1, future_time)

    with boa.env.prank(user), boa.reverts("only owner"):
        pool.stop_ramp_A_gamma()


def test_revert_ramp_too_far(pool, factory_admin):
    # sanity check: ramping is not active
    assert pool.initial_A_gamma_time() == 0

    A = pool.A()
    gamma = pool.gamma()
    future_time = boa.env.evm.patch.timestamp + UNIX_DAY + 1

    with boa.env.prank(factory_admin), boa.reverts("A change too high"):
        future_A = A * 11  # can at most increase by 10x
        pool.ramp_A_gamma(future_A, gamma, future_time)
    with boa.env.prank(factory_admin), boa.reverts("A change too low"):
        future_A = A // 11  # can at most decrease by 10x
        pool.ramp_A_gamma(future_A, gamma, future_time)

    with boa.env.prank(factory_admin), boa.reverts("gamma change too high"):
        future_gamma = gamma * 11  # can at most increase by 10x
        pool.ramp_A_gamma(A, future_gamma, future_time)
    with boa.env.prank(factory_admin), boa.reverts("gamma change too low"):
        future_gamma = gamma // 11  # can at most decrease by 10x
        pool.ramp_A_gamma(A, future_gamma, future_time)
