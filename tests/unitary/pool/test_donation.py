import boa
from tests.utils.constants import N_COINS
from pytest import fixture
import pytest
import math


def test_cant_donate_on_empty_pool(gm_pool):
    with boa.reverts("empty pool"):
        gm_pool.donate([10**18, 2 * 10**18])


@fixture()
def gm_pool_with_liquidity(gm_pool):
    gm_pool.add_liquidity_balanced(1000 * 10**18)
    return gm_pool


def test_donate(gm_pool_with_liquidity):
    pool = gm_pool_with_liquidity
    assert (
        pool.unabsorbed_xcp() == 0
    ), "unabsorbed xcp should be 0 before any donation has been sent"
    assert pool.dead_xcp() == 0, "dead xcp should be 0 before any donation has been sent"

    HALF_DONATION_DOLLAR_VALUE = 10 * 10**18  # 20 dollars
    old_virtual_price = pool.virtual_price()
    old_balances = [pool.balances(i) for i in range(N_COINS)]
    old_xcp_profit = pool.xcp_profit()
    pool.donate_balanced(HALF_DONATION_DOLLAR_VALUE)
    donated_amounts = pool.compute_balanced_amounts(HALF_DONATION_DOLLAR_VALUE)
    assert (
        pool.virtual_price() == old_virtual_price
    ), "donations should not affect virtual price before they get absorbed"
    assert pool.xcp_profit() == old_xcp_profit, "donations should not affect xcp profit"
    for i in range(N_COINS):
        assert (
            pool.balances(i) == old_balances[i] + donated_amounts[i]
        ), "donations should increase balances"

    assert (
        pool.unabsorbed_xcp() > 0
    ), "donation xcp should be greater than 0 after a donation has been sent"
    assert pool.dead_xcp() > 0, "dead xcp should be greater than 0 after a donation has been sent"


def test_absorption(gm_pool_with_liquidity):
    pool = gm_pool_with_liquidity

    HALF_DONATION_DOLLAR_VALUE = 10 * 10**18  # 20 dollars
    donated_amounts = pool.compute_balanced_amounts(HALF_DONATION_DOLLAR_VALUE)
    pool.donate(donated_amounts)

    assert pool.dead_xcp() > 0, "dead xcp should be greater than 0 after a donation has been sent"
    assert (
        pool.unabsorbed_xcp() > 0
    ), "unabsorbed xcp should be greater than 0 after a donation has been sent"

    old_unabsorbed_xcp = pool.unabsorbed_xcp()
    old_dead_xcp = pool.dead_xcp()
    old_virtual_price = pool.virtual_price()
    old_xcp_profit = pool.xcp_profit()

    for i in range(86400 * 7 // 1000):
        boa.env.time_travel(seconds=1)
        pool.internal._absorb_donation()

        assert (
            pool.unabsorbed_xcp() < old_unabsorbed_xcp
        ), "unabsorbed xcp should decrease after absorption"
        assert (
            pool.virtual_price() > old_virtual_price
        ), "virtual price should increase after absorption"
        assert pool.xcp_profit() == old_xcp_profit, "xcp profit should not change after absorption"
        assert pool.dead_xcp() == old_dead_xcp, "dead xcp should stay the same during absorption"

        old_dead_xcp = pool.dead_xcp()
        old_unabsorbed_xcp = pool.unabsorbed_xcp()
        old_virtual_price = pool.virtual_price()
        old_xcp_profit = pool.xcp_profit()


def test_slippage(gm_pool_with_liquidity, views_contract):
    pool = gm_pool_with_liquidity
    DONATION_AMOUNT = pool.compute_balanced_amounts(10 * 10**18)

    expected_amount = views_contract.calc_donate(pool, DONATION_AMOUNT)

    # Donation should pass if no operation happened before.
    with boa.env.anchor():
        pool.donate(DONATION_AMOUNT, slippage=expected_amount)

    # Even a small change before donation should revert because of slippage.
    pool.add_liquidity_balanced(10**18)

    with boa.reverts("donation slippage"):
        pool.donate(DONATION_AMOUNT, slippage=expected_amount)


def test_donation_ratio_too_high(gm_pool_with_liquidity):
    pool = gm_pool_with_liquidity
    balances = [pool.balances(i) for i in range(N_COINS)]
    donation_amounts = [balance // 9 for balance in balances]

    # This should not revert because we're maxing out the allowed ratio
    # but not exceeding it.
    with boa.env.anchor():
        pool.donate(donation_amounts)

    donation_amounts = [int(amount * 1.1) for amount in donation_amounts]

    with boa.reverts("ratio too high"):
        pool.donate(donation_amounts)


@pytest.mark.parametrize("time_elapsed", [1, 86400, 86400 * 7, 86400 * 30])
def test_reset_elapsed_time(gm_pool_with_liquidity, time_elapsed):
    pool = gm_pool_with_liquidity

    assert (
        pool.last_donation_absorb_timestamp() == 0
    ), "absorb timestamp should be zero if donations never occurred"

    boa.env.time_travel(seconds=time_elapsed)
    pool.donate_balanced(10 * 10**15)

    atomic_double_unabsorbed_xcp = None
    with boa.env.anchor():
        pool.donate_balanced(10 * 10**15)
        atomic_double_unabsorbed_xcp = pool.unabsorbed_xcp()

    assert (
        pool.last_donation_absorb_timestamp() == boa.env.timestamp
    ), "absorb timestamp should be updated, donation occurred for the first time"

    # this is the logic in the code to computed the absorbed amount
    absorbed_amount = min(
        pool.unabsorbed_xcp(), pool.unabsorbed_xcp() * time_elapsed // pool.donation_duration()
    )

    boa.env.time_travel(seconds=time_elapsed)
    pool.donate_balanced(10 * 10**15)

    assert (
        pool.last_donation_absorb_timestamp() == boa.env.timestamp
    ), "absorb timestamp should be updated, donation occurred for the second time"

    # this test makes sure that given a double donation, a part of the first
    # donation has been absorbed and the rest is still in the donation buffer.
    assert (
        pool.unabsorbed_xcp() == atomic_double_unabsorbed_xcp - absorbed_amount
    ), "unabsorbed xcp should be less than atomic double donation"


def test_add_liquidity_isnt_affected_by_donations(gm_pool_with_liquidity):
    pool = gm_pool_with_liquidity

    with boa.env.anchor():
        expected_user_lp_tokens = pool.add_liquidity_balanced(10**18)

    pool.donate_balanced(10**18)
    actual_user_lp_tokens = pool.add_liquidity_balanced(10**18)

    assert (
        expected_user_lp_tokens == actual_user_lp_tokens
    ), "user lp tokens should be the same before and after donation"


def test_remove_liquidity_isnt_affected_by_donations(gm_pool_with_liquidity):
    pool = gm_pool_with_liquidity

    user_lp_tokens = pool.add_liquidity_balanced(10**18)

    with boa.env.anchor():
        expected_user_tokens = pool.remove_liquidity(user_lp_tokens, [0, 0])

    pool.donate_balanced(10**18)
    actual_user_tokens = pool.remove_liquidity(user_lp_tokens, [0, 0])

    # we allow the values in these arrays to be off by one because of rounding
    for expected, actual in zip(expected_user_tokens, actual_user_tokens):
        assert math.isclose(
            expected, actual, abs_tol=1
        ), "user withdrawn tokens should be the same before and after donation"


# @pytest.mark.xfail
@pytest.mark.parametrize("i", range(N_COINS))
def test_remove_liquidity_fixed_out(gm_pool_with_liquidity, i):
    pool = gm_pool_with_liquidity

    user_lp_tokens = pool.add_liquidity_balanced(10**18)
    amounts_in = pool.compute_balanced_amounts(10**18)

    with boa.env.anchor():
        expected_user_tokens_j = pool.remove_liquidity_fixed_out(
            user_lp_tokens, i, int(amounts_in[i] * 0.1), 0
        )

    pool.donate_balanced(10**18)
    actual_user_tokens_j = pool.remove_liquidity_fixed_out(
        user_lp_tokens, i, int(amounts_in[i] * 0.1), 0
    )

    assert (
        expected_user_tokens_j == actual_user_tokens_j
    ), "user withdrawn tokens should be the same before and after donation"


@pytest.mark.parametrize("i", range(N_COINS))
def test_donation_improves_swap_liquidity(gm_pool_with_liquidity, i):
    pool = gm_pool_with_liquidity

    AMOUNT = 10**18

    with boa.env.anchor():
        pre_donation_dy = pool.exchange(i, AMOUNT)

    pool.donate_balanced(10**18)

    with boa.env.anchor():
        post_donation_dy = pool.exchange(i, AMOUNT)

    assert (
        post_donation_dy > pre_donation_dy
    ), "donation should improve swap liquidity, dy should increase"
