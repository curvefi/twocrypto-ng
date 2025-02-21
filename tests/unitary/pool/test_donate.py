import math
import boa
import pytest

from tests.unitary.utils import GodModePool
from tests.utils.constants import N_COINS


@pytest.fixture
def pool(swap_with_deposit, coins):
    return GodModePool(swap_with_deposit, coins)


def test_donation(pool, coins):
    DONATION_AMOUNT = [10**18, 2 * 10**18]

    old_balances = [pool.balances(i) for i in range(N_COINS)]
    old_donation_balances = [pool.donation_balances(i) for i in range(N_COINS)]

    assert all(old_donation_balances) == 0, "initial donation balances should be 0"
    assert all(old_balances) != 0, "initial balances should be greater than 0"

    pool.donate(DONATION_AMOUNT)

    balances = [pool.balances(i) for i in range(N_COINS)]
    donation_balances = [pool.donation_balances(i) for i in range(N_COINS)]
    balance_of = [coin.balanceOf(pool) for coin in coins]

    for i in range(N_COINS):
        assert balances[i] == old_balances[i], "balance should not increase after donation"
        assert (
            donation_balances[i] == DONATION_AMOUNT[i]
        ), "donation balance should be equal to donation amount"
        assert (
            balance_of[i] == balances[i] + donation_balances[i]
        ), "token-tracked balance should be equal to balance + donation balance"


def test_unabsorbed_donation_cant_be_withdrawn(pool, coins):
    DONATION_AMOUNT = [10**18, 2 * 10**18]
    pool.donate(DONATION_AMOUNT)

    for coin in coins:
        assert coin.balanceOf(pool) > 0, "all coins should be withdrawn"

    lp_token_holders = pool._storage.balanceOf.get()
    assert len(lp_token_holders) == 1, "should only have one LP token holder"

    for holder, amount in lp_token_holders.items():
        pool.remove_liquidity(amount, [0] * N_COINS, sender=holder)

    lp_token_holders = pool._storage.balanceOf.get()
    assert len(lp_token_holders) == 0, "all LP tokens should be withdrawn"

    for i in range(N_COINS):
        assert (
            coins[i].balanceOf(pool) == DONATION_AMOUNT[i]
        ), "only coins left should be donate funds"


# TODO test removal case 1


def test_absorbed_donation_cant_be_withdrawn(pool, coins):
    DONATION_AMOUNT = [coins[i].balanceOf(pool) for i in range(N_COINS)]
    pool.donate(DONATION_AMOUNT)

    for coin in coins:
        assert coin.balanceOf(pool) > 0, "all coins should be withdrawn"

    lp_token_holders = pool._storage.balanceOf.get()
    assert len(lp_token_holders) == 1, "should only have one LP token holder"

    # we move 7 days into the future to fully absorb the donation
    boa.env.time_travel(86400 * 100000)

    for holder, amount in lp_token_holders.items():
        pool.remove_liquidity(amount, [0] * N_COINS, sender=holder)

    lp_token_holders = pool._storage.balanceOf.get()
    assert len(lp_token_holders) == 0, "all LP tokens should be withdrawn"

    # TODO
    for i in range(N_COINS):
        assert math.isclose(
            coins[i].balanceOf(pool), DONATION_AMOUNT[i], rel_tol=0.00001
        ), "only coins left should be donate funds"


def test_absorption(pool):
    amount = 100 * 10**18
    DONATION_AMOUNT = [int(amount), int(amount * 1e18 // pool.price_scale())]
    RATE = 10**15
    INCREASES = min(DONATION_AMOUNT[i] // RATE for i in range(N_COINS))

    def absorb(seconds):
        boa.env.time_travel(seconds=seconds)
        pool.internal._absorb_donation()
        return [pool.balances(0), pool.balances(1)], [
            pool.donation_balances(0),
            pool.donation_balances(1),
        ]

    pool.donate(DONATION_AMOUNT)
    balances, donation_balances = absorb(0)
    constant_sum = [balances[i] + donation_balances[i] for i in range(N_COINS)]
    virtual_price = pool.virtual_price()
    xcp_profit = pool.xcp_profit()
    D = pool.D()
    for _ in range(INCREASES):
        new_balances, new_donation_balances = absorb(1)
        new_D = pool.D()
        new_virtual_price = pool.virtual_price()
        new_xcp_profit = pool.xcp_profit()

        assert new_D > D, "D should be strictly increasing"
        assert new_virtual_price > virtual_price, "virtual price should be strictly increasing"
        assert new_xcp_profit == xcp_profit, "xcp profit should be constant"
        for i in reversed(range(N_COINS)):
            assert (
                new_balances[i] == balances[i] + RATE
            ), "balances should increase at a constant rate"
            assert (
                new_donation_balances[i] == donation_balances[i] - RATE
            ), "donation balances should decrease at a constant rate"
            assert (
                new_balances[i] + new_donation_balances[i] == constant_sum[i]
            ), "sum of balances should be constant"

        # Update values
        balances, donation_balances = new_balances, new_donation_balances
        virtual_price = new_virtual_price
        xcp_profit = new_xcp_profit
        D = new_D
