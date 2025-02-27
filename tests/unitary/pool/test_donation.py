import boa
import pytest
from tests.unitary.utils import GodModePool
from tests.utils.constants import N_COINS


@pytest.fixture
def pool(swap_with_deposit, coins):
    return GodModePool(swap_with_deposit, coins)


def test_cant_donate_on_empty_pool(pool):
    pass  # TODO


def test_donate(pool):
    assert pool.donation_xcp() == 0, "donation xcp should be 0 before any donation has been sent"

    DONATION_AMOUNTS = [10**18, 2 * 10**18]
    old_virtual_price = pool.virtual_price()
    old_balances = [pool.balances(i) for i in range(N_COINS)]
    old_xcp_profit = pool.xcp_profit()
    pool.donate(DONATION_AMOUNTS)
    assert (
        pool.virtual_price() == old_virtual_price
    ), "donations should not affect virtual price before they get absorbed"
    assert pool.xcp_profit() == old_xcp_profit, "donations should not affect xcp profit"
    for i in range(N_COINS):
        assert (
            pool.balances(i) == old_balances[i] + DONATION_AMOUNTS[i]
        ), "donations should increase balances"

    assert (
        pool.donation_xcp() > 0
    ), "donation xcp should be greater than 0 after a donation has been sent"


def test_absorption(pool):
    DONATION_AMOUNTS = [10**18, 2 * 10**18]
    pool.donate(DONATION_AMOUNTS)

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


def test_slippage(pool, views_contract):
    DONATION_AMOUNT = [10**18, 2 * 10**18]

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
    pool.add_liquidity([10**18, 10**18])

    with boa.reverts("donation slippage"):
        pool.donate(DONATION_AMOUNT, slippage=expected_amount)


def test_donation_ratio_too_high(pool):
    pass  # TODO


#     balances = [pool.balances(i) for i in range(N_COINS)]
#     donation_amounts = [balance // 9 for balance in balances]

#     # This should not revert because we're maxing out the allowed ratio
#     # but not exceeding it.
#     with boa.env.anchor():
#         pool.donate(donation_amounts)

#     donation_amounts = [int(amount * 1.1) for amount in donation_amounts]

#     with boa.reverts("ratio too high"):
#         pool.donate(donation_amounts)
