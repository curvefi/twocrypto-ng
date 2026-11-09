"""
Ramps to the ends of the cryptoswap A and gamma ranges, and a swap at each end.
"""

import boa
import pytest

from tests.conftest import INITIAL_PRICES, _crypto_swap_with_deposit, _deploy_pool
from tests.utils.constants import MAX_A, MAX_GAMMA, MIN_A, MIN_GAMMA, POOL_DEPLOYER, UNIX_DAY


def _funded_pool(factory, coins, params, deployer, user, **overrides):
    pool = POOL_DEPLOYER.at(_deploy_pool(factory, {**params, **overrides}, coins, deployer))
    return _crypto_swap_with_deposit(coins, user, pool, INITIAL_PRICES)


def _swap(pool, coins, user, i):
    dx = pool.balances(i) // 1_000
    boa.deal(coins[i], user, dx)
    return pool.exchange(i, 1 - i, dx, 0, sender=user)


@pytest.mark.parametrize(
    "start, target, beyond, reason, field",
    [
        (MIN_A * 10, MIN_A, MIN_A - 1, '"A below minimum"', "A"),
        (MAX_A // 10, MAX_A, MAX_A + 1, '"A above maximum"', "A"),
        (MIN_GAMMA * 10, MIN_GAMMA, MIN_GAMMA - 1, '"gamma below minimum"', "gamma"),
        (MAX_GAMMA // 10, MAX_GAMMA, MAX_GAMMA + 1, '"gamma above maximum"', "gamma"),
    ],
)
def test_ramp_to_bound(
    factory, coins, params, deployer, user, factory_admin, start, target, beyond, reason, field
):
    pool = _funded_pool(factory, coins, params, deployer, user, **{field: start})
    future_time = boa.env.evm.patch.timestamp + UNIX_DAY

    def ramp(value):
        A, gamma = (value, pool.gamma()) if field == "A" else (pool.A(), value)
        pool.ramp_A_gamma(A, gamma, future_time, sender=factory_admin)

    with boa.reverts(dev=reason):
        ramp(beyond)
    ramp(target)

    boa.env.time_travel(UNIX_DAY + 1)
    assert (pool.A() if field == "A" else pool.gamma()) == target

    assert _swap(pool, coins, user, 0) > 0
    assert _swap(pool, coins, user, 1) > 0
