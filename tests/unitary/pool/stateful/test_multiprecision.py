import pytest
from boa.test import strategy
from hypothesis.stateful import rule, run_state_machine_as_test

from tests.unitary.pool.stateful.test_stateful import NumbaGoUp

MAX_SAMPLES = 100
STEP_COUNT = 100


@pytest.fixture(scope="module")
def coins(stgusdc):
    return stgusdc


@pytest.fixture(scope="module")
def swap(swap_multiprecision):
    return swap_multiprecision


class Multiprecision(NumbaGoUp):
    exchange_amount_in = strategy(
        "uint256", min_value=10**18, max_value=50000 * 10**18
    )
    user = strategy("address")
    exchange_i = strategy("uint8", max_value=1)

    @rule(
        exchange_amount_in=exchange_amount_in,
        exchange_i=exchange_i,
        user=user,
    )
    def exchange(self, exchange_amount_in, exchange_i, user):
        exchange_amount_in = exchange_amount_in // 10 ** (
            18 - self.decimals[exchange_i]
        )
        super().exchange(exchange_amount_in, exchange_i, user)


def test_multiprecision(users, coins, swap):
    from hypothesis import settings
    from hypothesis._settings import HealthCheck

    Multiprecision.TestCase.settings = settings(
        max_examples=MAX_SAMPLES,
        stateful_step_count=STEP_COUNT,
        suppress_health_check=list(HealthCheck),
        deadline=None,
    )

    for k, v in locals().items():
        setattr(Multiprecision, k, v)

    # because of this hypothesis.event does not work
    run_state_machine_as_test(Multiprecision)
