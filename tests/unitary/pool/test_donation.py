import boa
from tests.utils.constants import N_COINS
from pytest import fixture


def test_cant_donate_on_empty_pool(gm_pool):
    with boa.reverts("empty pool"):
        gm_pool.donate([10**18, 2 * 10**18])


@fixture()
def gm_pool_with_liquidity(gm_pool):
    gm_pool.add_liquidity_balanced(1000 * 10**18)
    return gm_pool


def test_donate(gm_pool_with_liquidity):
    pool = gm_pool_with_liquidity
    assert pool.donation_xcp() == 0, "donation xcp should be 0 before any donation has been sent"

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
        pool.donation_xcp() > 0
    ), "donation xcp should be greater than 0 after a donation has been sent"


def test_absorption(gm_pool_with_liquidity):
    pool = gm_pool_with_liquidity

    HALF_DONATION_DOLLAR_VALUE = 10 * 10**18  # 20 dollars
    donated_amounts = pool.compute_balanced_amounts(HALF_DONATION_DOLLAR_VALUE)
    pool.donate(donated_amounts)

    assert (
        pool.donation_xcp() > 0
    ), "donation xcp should be greater than 0 after a donation has been sent"

    old_donation_xcp = pool.donation_xcp()
    old_virtual_price = pool.virtual_price()
    old_xcp_profit = pool.xcp_profit()

    for i in range(86400 * 7 // 1000):
        boa.env.time_travel(seconds=1)
        pool.absorb_donation()

        assert (
            pool.donation_xcp() < old_donation_xcp
        ), "donation xcp should decrease after absorption"
        assert (
            pool.virtual_price() > old_virtual_price
        ), "virtual price should increase after absorption"
        assert pool.xcp_profit() == old_xcp_profit, "xcp profit should not change after absorption"

        old_donation_xcp = pool.donation_xcp()
        old_virtual_price = pool.virtual_price()
        old_xcp_profit = pool.xcp_profit()


def test_slippage(gm_pool_with_liquidity, views_contract):
    pool = gm_pool_with_liquidity
    DONATION_AMOUNT = pool.compute_balanced_amounts(10 * 10**18)

    expected_amount = views_contract.calc_token_amount(
        DONATION_AMOUNT,
        True,
        pool.address,
        True,  # Donation mode is enabled.
    )

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
