import boa
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    initialize,
    invariant,
    precondition,
    rule,
    run_state_machine_as_test,
)

from tests.unitary.pool.stateful.legacy.test_stateful import NumbaGoUp
from tests.utils.constants import (
    MAX_A,
    MAX_GAMMA,
    MIN_A,
    MIN_GAMMA,
    MIN_RAMP_TIME,
    UNIX_DAY,
)

MAX_SAMPLES = 20
STEP_COUNT = 100

# [0.2, 0.3 ... 0.9, 1, 2, 3 ... 10], used as sample values for the ramp step
change_steps = [x / 10 if x < 10 else x for x in range(2, 11)] + list(
    range(2, 11)
)


class RampTest(NumbaGoUp):
    """
    This class tests statefully tests wheter ramping A and
    gamma does not break the pool. At the start it always start
    with a ramp, then it can ramp again.
    """

    # we can only ramp A and gamma at most 10x
    # lower/higher than their starting value
    change_step_strategy = st.sampled_from(change_steps)

    # we fuzz the ramp duration up to a year
    days = st.integers(min_value=1, max_value=365)

    def is_not_ramping(self):
        """
        Checks if the pool is not already ramping.
        TODO check condition in the pool as it looks weird
        """
        return (
            boa.env.evm.patch.timestamp
            > self.swap.initial_A_gamma_time() + (MIN_RAMP_TIME - 1)
        )

    @initialize(
        A_change=change_step_strategy,
        gamma_change=change_step_strategy,
        days=days,
    )
    def initial_ramp(self, A_change, gamma_change, days):
        """
        At the start of the stateful test, we always ramp.
        """
        self.__ramp(A_change, gamma_change, days)

    @precondition(is_not_ramping)
    @rule(
        A_change=change_step_strategy,
        gamma_change=change_step_strategy,
        days=days,
    )
    def ramp(self, A_change, gamma_change, days):
        """
        Additional ramping after the initial ramp.
        Pools might ramp multiple times during their lifetime.
        """
        self.__ramp(A_change, gamma_change, days)

    def __ramp(self, A_change, gamma_change, days):
        """
        Computes the new A and gamma values by multiplying the current ones
        by the change factors. Then clamps the new values to stay in the
        [MIN_A, MAX_A] and [MIN_GAMMA, MAX_GAMMA] ranges.

        Then proceeds to ramp the pool with the new values (with admin rights).
        """
        new_A = self.swap.A() * A_change
        new_A = int(
            max(MIN_A, min(MAX_A, new_A))
        )  # clamp new_A to stay in [MIN_A, MAX_A]

        new_gamma = self.swap.gamma() * gamma_change
        new_gamma = int(
            max(MIN_GAMMA, min(MAX_GAMMA, new_gamma))
        )  # clamp new_gamma to stay in [MIN_GAMMA, MAX_GAMMA]

        # current timestamp + fuzzed days
        ramp_duration = boa.env.evm.patch.timestamp + days * UNIX_DAY

        self.swap.ramp_A_gamma(
            new_A,
            new_gamma,
            ramp_duration,
            sender=self.swap_admin,
        )

    @invariant()
    def up_only_profit(self):
        """
        We allow the profit to go down only because of the ramp.
        TODO we should still check that losses are not too big
        ideally something proportional to the ramp
        """
        pass

    @invariant()
    def virtual_price(self):
        """
        We allow the profit to go down only because of the ramp.
        TODO we should still check that losses are not too big
        ideally something proportional to the ramp
        """
        pass


def test_ramp(users, coins, swap):
    # TODO parametrize with different swaps
    RampTest.TestCase.settings = settings(
        max_examples=MAX_SAMPLES,
        stateful_step_count=STEP_COUNT,
        suppress_health_check=list(HealthCheck),
        deadline=None,
    )

    for k, v in locals().items():
        setattr(RampTest, k, v)

    # because of this hypothesis.event does not work
    run_state_machine_as_test(RampTest)
