import boa
from boa.test import strategy
from hypothesis.stateful import invariant, rule, run_state_machine_as_test

from tests.unitary.pool.stateful.test_stateful import NumbaGoUp

MAX_SAMPLES = 20
STEP_COUNT = 100
MAX_D = 10**12 * 10**18  # $1T is hopefully a reasonable cap for tests
ALLOWED_DIFFERENCE = 0.001


class RampTest(NumbaGoUp):
    check_out_amount = strategy("bool")
    exchange_amount_in = strategy(
        "uint256", min_value=10**18, max_value=50000 * 10**18
    )
    token_amount = strategy(
        "uint256", min_value=10**18, max_value=10**12 * 10**18
    )
    deposit_amounts = strategy(
        "uint256[3]", min_value=10**18, max_value=10**9 * 10**18
    )
    user = strategy("address")
    exchange_i = strategy("uint8", max_value=1)

    def setup(self, user_id=0):
        super().setup(user_id)
        new_A = self.swap.A() * 2
        new_gamma = self.swap.gamma() * 2
        self.swap.ramp_A_gamma(
            new_A,
            new_gamma,
            boa.env.vm.state.timestamp + 14 * 86400,
            sender=self.swap_admin,
        )

    @rule(
        user=user,
        exchange_i=exchange_i,
        exchange_amount_in=exchange_amount_in,
        check_out_amount=check_out_amount,
    )
    def exchange(self, exchange_amount_in, exchange_i, user, check_out_amount):

        if exchange_i > 0:
            exchange_amount_in = (
                exchange_amount_in * 10**18 // self.swap.price_oracle()
            )
            if exchange_amount_in < 1000:
                return

        super()._exchange(
            exchange_amount_in,
            exchange_i,
            user,
            ALLOWED_DIFFERENCE if check_out_amount else False,
        )

    @rule(
        user=user,
        token_amount=token_amount,
        exchange_i=exchange_i,
        check_out_amount=check_out_amount,
    )
    def remove_liquidity_one_coin(
        self, token_amount, exchange_i, user, check_out_amount
    ):

        if check_out_amount:
            super().remove_liquidity_one_coin(
                token_amount, exchange_i, user, ALLOWED_DIFFERENCE
            )
        else:
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
