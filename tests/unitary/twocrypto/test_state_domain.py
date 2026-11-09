"""
Committed states stay inside the math's domain.

tweak_price refuses to commit a state whose D or balances lie outside the range
TwocryptoMath.get_y accepts at the current gamma, and declines a rebalance whose
new state would. Without this, a successful deposit or rebalance could leave a
pool where every later swap and one-coin withdrawal reverts.

Each test also rebuilds the normalized balances from what is actually stored
(balances and price scale) after every successful operation and checks the same
predicate there, not just on the vector the pool computed.
"""

import boa
import pytest

from tests.conftest import _deploy_pool
from tests.utils.constants import POOL_DEPLOYER
from tests.utils.god_mode import GodModePool

MAX_GAMMA = 199 * 10**15


def _new_pool(factory, coins, params, deployer, **overrides):
    p = {**params, "initial_prices": [10**18, 10**18], **overrides}
    return POOL_DEPLOYER.at(_deploy_pool(factory, p, coins, deployer))


def _assert_stored_state_in_domain(pool):
    balances = [pool.balances(0), pool.balances(1)]
    xp = pool.internal._xp(balances, pool.price_scale())
    assert pool.internal._in_domain(xp, pool.D(), pool.gamma()), (balances, pool.D())


@pytest.mark.parametrize("gamma, admitted", [(145 * 10**12, True), (MAX_GAMMA, False)])
def test_one_sided_deposit_that_would_freeze_swaps(
    factory, coins, params, deployer, gamma, admitted
):
    pool = _new_pool(factory, coins, params, deployer, A=4_000_000, gamma=gamma)
    gm_pool = GodModePool(pool)
    gm_pool.add_liquidity([10**24, 10**24])
    boa.env.time_travel(seconds=600)

    # one-sided deposit to about 50:1: fine at low gamma, outside get_y's
    # range at maximum gamma (the light balance would be about 2.7% of D)
    deposit = [49 * 10**24, 0]
    if admitted:
        gm_pool.add_liquidity(deposit)
    else:
        with boa.reverts("!balance"):
            gm_pool.add_liquidity(deposit)
    _assert_stored_state_in_domain(pool)

    # either way, swaps in both directions still work
    boa.env.time_travel(seconds=600)
    assert gm_pool.exchange(0, pool.balances(0) // 10**4) > 0
    assert gm_pool.exchange(1, pool.balances(1) // 10**4) > 0
    _assert_stored_state_in_domain(pool)


def test_rebalance_near_lower_D_bound_is_declined(factory, coins, params, deployer):
    # seeded just above the D floor; one-way swaps move the oracle until a
    # rebalance would lower D below 1e17 (it did before the guard)
    pool = _new_pool(factory, coins, params, deployer)
    gm_pool = GodModePool(pool)
    gm_pool.add_liquidity([5 * 10**16 + 10**14, 5 * 10**16 + 10**14])

    for _ in range(10):
        boa.env.time_travel(seconds=3600)
        gm_pool.exchange(1, pool.balances(1) // 50)
        assert pool.D() >= 10**17
        _assert_stored_state_in_domain(pool)

    # the next quote and swap still work
    dx = 10**14
    quote = pool.get_dy(0, 1, dx)
    assert gm_pool.exchange(0, dx) == quote


@pytest.mark.parametrize("zero_fee_split", [False, True])
@pytest.mark.parametrize("gamma", [145 * 10**12, 63 * 10**15, MAX_GAMMA])
def test_stored_state_stays_in_domain(
    factory, coins, params, deployer, factory_admin, gamma, zero_fee_split
):
    pool = _new_pool(factory, coins, params, deployer, A=4_000_000, gamma=gamma)
    if zero_fee_split:
        # withdrawals then commit the solver's balances instead of rebuilding
        # them from storage (Twocrypto.vy, _remove_liquidity_fixed_out)
        pool.set_fee_parameters(0, 0, sender=factory_admin)
    gm_pool = GodModePool(pool)
    gm_pool.add_liquidity([10**24, 10**24])
    lp = pool.balanceOf(boa.env.eoa)

    succeeded = {"swap": 0, "deposit": 0, "withdrawal": 0}
    rebalances = 0
    for k in range(80):
        boa.env.time_travel(seconds=600 + 97 * k)
        i = k % 2
        size = pool.balances(i) // (2 + (k * 7) % 11)
        action = k % 4
        scale_before = pool.price_scale()
        try:
            if action == 0:
                gm_pool.exchange(i, size)
                kind = "swap"
            elif action == 1:
                amounts = [0, 0]
                amounts[i] = size
                gm_pool.add_liquidity(amounts)
                kind = "deposit"
            elif action == 2:
                gm_pool.exchange(1 - i, pool.balances(1 - i) // (3 + k % 5))
                kind = "swap"
            else:
                pool.remove_liquidity_one_coin(lp // 80, i, 0)
                kind = "withdrawal"
        except boa.BoaError:
            continue
        succeeded[kind] += 1
        if pool.price_scale() != scale_before:
            rebalances += 1
        _assert_stored_state_in_domain(pool)

    # every kind of operation, and at least one accepted rebalance, was
    # exercised and checked against the stored state
    assert all(count > 0 for count in succeeded.values()), succeeded
    assert rebalances > 0
