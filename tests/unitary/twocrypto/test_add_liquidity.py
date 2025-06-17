import math

import boa
import pytest

from tests.utils.constants import N_COINS
from tests.utils.god_mode import GodModePool

PRECISION = 10**18
INITIAL_LIQUIDITY = 1000 * PRECISION


@pytest.fixture(scope="module")
def user_account():
    return boa.env.generate_address()


@pytest.fixture(scope="module")
def bob():
    return boa.env.generate_address()


@pytest.fixture(scope="module")
def charlie():
    return boa.env.generate_address()


def test_add_liquidity_empty_pool(pool, user_account):
    gm_pool = GodModePool(pool)
    amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY)

    gm_pool.premint_amounts(amounts, to=user_account)
    minted_lp = pool.add_liquidity(amounts, 0, sender=user_account)

    assert minted_lp > 0
    assert pool.balanceOf(user_account) == minted_lp
    assert pool.totalSupply() == minted_lp

    for i in range(N_COINS):
        assert pool.balances(i) == amounts[i]

    assert pool.D() > 0
    assert pool.virtual_price() == PRECISION


def test_add_liquidity_existing_pool(pool, user_account, bob):
    gm_pool = GodModePool(pool)

    # Initial liquidity from user_account
    initial_amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY)
    gm_pool.premint_amounts(initial_amounts, to=user_account)
    pool.add_liquidity(initial_amounts, 0, sender=user_account)

    initial_lp_total_supply = pool.totalSupply()
    initial_D = pool.D()
    initial_balances = [pool.balances(i) for i in range(N_COINS)]

    # Bob adds more liquidity
    add_amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY // 2)
    gm_pool.premint_amounts(add_amounts, to=bob)
    minted_lp = pool.add_liquidity(add_amounts, 0, sender=bob)

    assert minted_lp > 0
    assert pool.balanceOf(bob) == minted_lp
    assert pool.totalSupply() == initial_lp_total_supply + minted_lp

    for i in range(N_COINS):
        assert pool.balances(i) == initial_balances[i] + add_amounts[i]

    assert pool.D() > initial_D


def test_add_liquidity_unbalanced(pool, user_account):
    gm_pool = GodModePool(pool)

    # Initial balanced liquidity
    initial_amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY)
    gm_pool.premint_amounts(initial_amounts, to=user_account)
    pool.add_liquidity(initial_amounts, 0, sender=user_account)

    initial_lp_total_supply = pool.totalSupply()

    # Add unbalanced liquidity
    unbalanced_amounts = [INITIAL_LIQUIDITY, 0]
    gm_pool.premint_amounts(unbalanced_amounts, to=user_account)

    pool.add_liquidity(unbalanced_amounts, 0, sender=user_account)
    event = pool.get_logs()[-1]

    assert event.fee > 0
    assert event.token_supply > initial_lp_total_supply


def test_add_liquidity_slippage(pool, user_account):
    gm_pool = GodModePool(pool)
    amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY)

    gm_pool.add_liquidity(amounts, 0)  # seed pool

    gm_pool.premint_amounts(amounts, to=user_account)

    expected_lp = pool.calc_token_amount(amounts, True)

    with boa.reverts("slippage"):
        pool.add_liquidity(amounts, expected_lp + 1, sender=user_account)


def test_add_liquidity_fee_and_donation_protection(pool, user_account, bob, charlie):
    gm_pool = GodModePool(pool)
    # 0. seed pool
    initial_amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY)
    gm_pool.add_liquidity(initial_amounts)

    # 1. user_account adds initial liquidity.
    gm_pool.premint_amounts(initial_amounts, to=user_account)
    pool.add_liquidity(initial_amounts, 0, sender=user_account)
    event1 = pool.get_logs()[-1]
    minted_lp1 = pool.balanceOf(user_account)
    fee_rate1 = event1.fee / (minted_lp1 + event1.fee)

    # 2. bob adds liquidity right after. This should incur a penalty.
    bob_adds_amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY // 10)
    gm_pool.premint_amounts(bob_adds_amounts, to=bob)
    pool.add_liquidity(bob_adds_amounts, 0, sender=bob)
    event2 = pool.get_logs()[-1]
    minted_lp2 = pool.balanceOf(bob)
    fee_rate2 = event2.fee / (minted_lp2 + event2.fee)

    assert fee_rate2 > fee_rate1

    # 3. Time travel to the middle of the protection period.
    protection_period = pool.donation_protection_period()
    boa.env.time_travel(seconds=protection_period // 2)

    # 4. charlie adds liquidity. The fee should be lower than bob's.
    charlie_adds_amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY // 10)
    gm_pool.premint_amounts(charlie_adds_amounts, to=charlie)
    pool.add_liquidity(charlie_adds_amounts, 0, sender=charlie)
    event3 = pool.get_logs()[-1]
    minted_lp3 = pool.balanceOf(charlie)
    fee_rate3 = event3.fee / (minted_lp3 + event3.fee)

    assert fee_rate3 < fee_rate2

    # 5. Time travel after protection period.
    boa.env.time_travel(seconds=protection_period + 1)

    # 6. bob adds liquidity again. Fee should be back to base level.
    bob_adds_again_amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY // 10)
    gm_pool.premint_amounts(bob_adds_again_amounts, to=bob)
    bob_initial_lp = pool.balanceOf(bob)
    pool.add_liquidity(bob_adds_again_amounts, 0, sender=bob)
    event4 = pool.get_logs()[-1]
    minted_lp4 = pool.balanceOf(bob) - bob_initial_lp
    fee_rate4 = event4.fee / (minted_lp4 + event4.fee)

    assert math.isclose(fee_rate4, fee_rate1, rel_tol=0.1)
    assert fee_rate4 < fee_rate3


def test_add_liquidity_donation(pool, user_account, bob):
    gm_pool = GodModePool(pool)

    # bob adds initial liquidity
    initial_amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY)
    gm_pool.premint_amounts(initial_amounts, to=bob)
    pool.add_liquidity(initial_amounts, 0, sender=bob)

    initial_total_supply = pool.totalSupply()
    initial_donation_shares = pool.donation_shares()
    assert initial_donation_shares == 0

    # user donates
    donation_amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY // 10)
    gm_pool.premint_amounts(donation_amounts, to=user_account)

    minted_lp = pool.add_liquidity(
        donation_amounts, 0, boa.eval("empty(address)"), True, sender=user_account
    )

    # Check event
    event = pool.get_logs()[-2]
    assert event.donor == user_account
    assert list(event.token_amounts) == donation_amounts

    assert pool.totalSupply() == initial_total_supply + minted_lp
    assert pool.donation_shares() == initial_donation_shares + minted_lp
    assert pool.balanceOf(user_account) == 0  # No LP tokens for donor
    assert pool.balanceOf(bob) == initial_total_supply  # Bob's balance is unchanged
