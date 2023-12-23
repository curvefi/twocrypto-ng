import boa
from boa.test import strategy
from hypothesis.stateful import invariant, rule, run_state_machine_as_test

from tests.unitary.pool.stateful.test_stateful import NumbaGoUp

MAX_SAMPLES = 20
STEP_COUNT = 100
MAX_D = 10**12 * 10**18  # $1T is hopefully a reasonable cap for tests
ALLOWED_DIFFERENCE = 0.02


class RampTest(NumbaGoUp):
    future_gamma = strategy(
        "uint256",
        min_value=int(2.8e-4 * 1e18 / 9),
        max_value=int(2.8e-4 * 1e18 * 9),
    )
    future_A = strategy(
        "uint256",
        min_value=90 * 2**2 * 10000 // 9,
        max_value=90 * 2**2 * 10000 * 9,
    )
    check_out_amount = strategy("bool")
    exchange_amount_in = strategy(
        "uint256", min_value=10**18, max_value=50000 * 10**18
    )
    token_amount = strategy(
        "uint256", min_value=10**18, max_value=10**12 * 10**18
    )
    user = strategy("address")
    exchange_i = strategy("uint8", max_value=1)

    def initialize(self, future_A, future_gamma):
        self.swap.ramp_A_gamma(
            future_A,
            future_gamma,
            boa.env.vm.state.timestamp + 14 * 86400,
            sender=self.swap_admin,
        )

    @rule(
        exchange_amount_in=exchange_amount_in,
        exchange_i=exchange_i,
        user=user,
    )
    def exchange(self, exchange_amount_in, exchange_i, user):
        try:
            super()._exchange(exchange_amount_in, exchange_i, user, False)
        except Exception:
            if exchange_amount_in > 10**9:
                # Small swaps can fail at ramps
                raise

    @rule(token_amount=token_amount, exchange_i=exchange_i, user=user)
    def remove_liquidity_one_coin(self, token_amount, exchange_i, user):
        super().remove_liquidity_one_coin(
            token_amount, exchange_i, user, False
        )

    @invariant()
    def virtual_price(self):
        # Invariant is not conserved here
        pass


def test_ramp(users, coins, swap):
    from hypothesis import settings
    from hypothesis._settings import HealthCheck

    RampTest.TestCase.settings = settings(
        max_examples=MAX_SAMPLES,
        stateful_step_count=STEP_COUNT,
        suppress_health_check=HealthCheck.all(),
        deadline=None,
    )

    for k, v in locals().items():
        setattr(RampTest, k, v)

    run_state_machine_as_test(RampTest)
