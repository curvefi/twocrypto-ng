import boa
import pytest

from tests.utils.constants import N_COINS
from tests.utils.god_mode import GodModePool
import numpy as np

PRECISION = 10**18
INITIAL_LIQUIDITY_COIN0 = 1000 * PRECISION  # Amount of coin 0 for initial balanced liquidity

# Constants for the new test
USER_LP_ADD_AMOUNT_COIN0 = 700 * PRECISION
DONATION_ADD_AMOUNT_COIN0 = 300 * PRECISION
SECOND_USER_ADD_AMOUNT_COIN0 = 100 * PRECISION


def test_remove_liquidity_partial(pool, coins, bob):
    user_account = boa.env.eoa
    gm_pool = GodModePool(pool)

    lp_minted = gm_pool.add_liquidity_balanced(amount=INITIAL_LIQUIDITY_COIN0)
    assert lp_minted > 0, "Initial liquidity minting failed"

    initial_lp_balance_user = pool.balanceOf(user_account)
    initial_total_supply = pool.totalSupply()
    initial_pool_balances = [pool.balances(i) for i in range(N_COINS)]
    initial_d = pool.D()
    user_coin_balances_before_remove = [coins[i].balanceOf(user_account) for i in range(N_COINS)]

    assert initial_lp_balance_user == lp_minted

    lp_to_remove = initial_lp_balance_user // 2
    min_amounts_to_receive = [0] * N_COINS

    expected_withdraw_amounts = [
        initial_pool_balances[i] * lp_to_remove // initial_total_supply for i in range(N_COINS)
    ]

    actual_withdrawn_amounts = pool.remove_liquidity(
        lp_to_remove, min_amounts_to_receive, sender=user_account
    )

    for i in range(N_COINS):
        assert actual_withdrawn_amounts[i] == expected_withdraw_amounts[i]

    # Verify event was emitted
    event_collection = pool.get_logs()
    remove_liquidity_event = None
    for e in event_collection:
        if "RemoveLiquidity" in str(e):
            remove_liquidity_event = e
            break
    assert remove_liquidity_event is not None, "RemoveLiquidity event not found"

    assert remove_liquidity_event.provider == user_account
    assert remove_liquidity_event.token_supply == initial_total_supply - lp_to_remove
    for i in range(N_COINS):
        assert remove_liquidity_event.token_amounts[i] == expected_withdraw_amounts[i]

    assert pool.balanceOf(user_account) == initial_lp_balance_user - lp_to_remove
    assert pool.totalSupply() == initial_total_supply - lp_to_remove

    final_pool_balances = [pool.balances(i) for i in range(N_COINS)]
    for i in range(N_COINS):
        assert final_pool_balances[i] == initial_pool_balances[i] - expected_withdraw_amounts[i]
        assert (
            coins[i].balanceOf(user_account)
            == user_coin_balances_before_remove[i] + expected_withdraw_amounts[i]
        )

    expected_d = initial_d - (initial_d * lp_to_remove // initial_total_supply)
    assert pool.D() == expected_d


def test_remove_liquidity_all(pool, coins, bob):
    user_account = boa.env.eoa
    gm_pool = GodModePool(pool)

    lp_minted = gm_pool.add_liquidity_balanced(amount=INITIAL_LIQUIDITY_COIN0)
    assert lp_minted > 0, "Initial liquidity minting failed"

    initial_lp_balance_user = pool.balanceOf(user_account)
    initial_total_supply = pool.totalSupply()
    initial_pool_balances = [pool.balances(i) for i in range(N_COINS)]
    user_coin_balances_before_remove = [coins[i].balanceOf(user_account) for i in range(N_COINS)]

    assert (
        initial_lp_balance_user == initial_total_supply
    )  # User (via GodMode) provided all liquidity

    lp_to_remove = initial_lp_balance_user
    min_amounts_to_receive = [0] * N_COINS

    expected_withdraw_amounts = initial_pool_balances

    actual_withdrawn_amounts = pool.remove_liquidity(
        lp_to_remove, min_amounts_to_receive, sender=user_account
    )

    for i in range(N_COINS):
        assert actual_withdrawn_amounts[i] == expected_withdraw_amounts[i]

    # Verify event was emitted
    event_collection = pool.get_logs()
    remove_liquidity_event = None
    for e in event_collection:
        if "RemoveLiquidity" in str(e):
            remove_liquidity_event = e
            break
    assert remove_liquidity_event is not None, "RemoveLiquidity event not found"

    assert remove_liquidity_event.provider == user_account
    assert remove_liquidity_event.token_supply == 0
    for i in range(N_COINS):
        assert remove_liquidity_event.token_amounts[i] == expected_withdraw_amounts[i]

    assert pool.balanceOf(user_account) == 0
    assert pool.totalSupply() == 0
    final_pool_balances = [pool.balances(i) for i in range(N_COINS)]
    for i in range(N_COINS):
        assert final_pool_balances[i] == 0
        assert (
            coins[i].balanceOf(user_account)
            == user_coin_balances_before_remove[i] + expected_withdraw_amounts[i]
        )

    assert pool.D() == 0


def test_remove_liquidity_slippage(pool, coins, bob):
    user_account = boa.env.eoa
    gm_pool = GodModePool(pool)

    lp_minted = gm_pool.add_liquidity_balanced(amount=INITIAL_LIQUIDITY_COIN0)
    assert lp_minted > 0, "Initial liquidity minting failed"

    initial_lp_balance_user = pool.balanceOf(user_account)
    initial_total_supply = pool.totalSupply()
    initial_pool_balances = [pool.balances(i) for i in range(N_COINS)]

    lp_to_remove = initial_lp_balance_user // 2

    expected_withdraw_amounts = [
        initial_pool_balances[i] * lp_to_remove // initial_total_supply for i in range(N_COINS)
    ]

    min_amounts_too_high = [val + 1 for val in expected_withdraw_amounts]
    if (
        not any(expected_withdraw_amounts)
        and any(val > 0 for val in initial_pool_balances)
        and lp_to_remove > 0
    ):
        for i in range(N_COINS):
            if (
                initial_pool_balances[i] * lp_to_remove // initial_total_supply == 0
                and initial_pool_balances[i] > 0
            ):
                min_amounts_too_high[i] = 1
                break
        else:
            if N_COINS > 0:
                min_amounts_too_high[0] = 1
    elif not any(expected_withdraw_amounts) and N_COINS > 0:
        min_amounts_too_high[0] = 1

    with pytest.raises(boa.BoaError) as e_info:
        pool.remove_liquidity(lp_to_remove, min_amounts_too_high, sender=user_account)

    assert "slippage" in str(e_info.value).lower()


def test_remove_liquidity_zero_amount(pool, coins, bob):
    user_account = boa.env.eoa
    gm_pool = GodModePool(pool)

    lp_minted = gm_pool.add_liquidity_balanced(amount=INITIAL_LIQUIDITY_COIN0)
    assert lp_minted > 0, "Initial liquidity minting failed"

    initial_lp_balance_user = pool.balanceOf(user_account)
    initial_total_supply = pool.totalSupply()
    initial_pool_balances = [pool.balances(i) for i in range(N_COINS)]
    initial_d = pool.D()
    user_coin_balances_before_remove = [coins[i].balanceOf(user_account) for i in range(N_COINS)]

    lp_to_remove = 0
    min_amounts_to_receive = [0] * N_COINS

    actual_withdrawn_amounts = pool.remove_liquidity(
        lp_to_remove, min_amounts_to_receive, sender=user_account
    )

    for i in range(N_COINS):
        assert actual_withdrawn_amounts[i] == 0

    # Verify event was emitted
    event_collection = pool.get_logs()
    remove_liquidity_event = None
    for e in event_collection:
        if "RemoveLiquidity" in str(e):
            remove_liquidity_event = e
            break
    assert remove_liquidity_event is not None, "RemoveLiquidity event not found"

    assert remove_liquidity_event.provider == user_account
    assert remove_liquidity_event.token_supply == initial_total_supply
    for i in range(N_COINS):
        assert remove_liquidity_event.token_amounts[i] == 0

    assert pool.balanceOf(user_account) == initial_lp_balance_user
    assert pool.totalSupply() == initial_total_supply
    final_pool_balances = [pool.balances(i) for i in range(N_COINS)]
    for i in range(N_COINS):
        assert final_pool_balances[i] == initial_pool_balances[i]
        assert coins[i].balanceOf(user_account) == user_coin_balances_before_remove[i]
    assert pool.D() == initial_d


def test_remove_liquidity_to_different_receiver(pool, coins, bob):
    user_account = boa.env.eoa
    gm_pool = GodModePool(pool)

    assert user_account != bob, "user_account (boa.env.eoa) and bob must be different for this test"

    lp_minted = gm_pool.add_liquidity_balanced(amount=INITIAL_LIQUIDITY_COIN0)
    assert lp_minted > 0, "Initial liquidity minting failed"

    initial_lp_balance_user = pool.balanceOf(user_account)
    initial_total_supply = pool.totalSupply()
    initial_pool_balances = [pool.balances(i) for i in range(N_COINS)]
    initial_d = pool.D()
    user_coin_balances_before_remove = [coins[i].balanceOf(user_account) for i in range(N_COINS)]
    bob_coin_balances_before_action = [coins[i].balanceOf(bob) for i in range(N_COINS)]

    lp_to_remove = initial_lp_balance_user // 2
    min_amounts_to_receive = [0] * N_COINS

    expected_withdraw_amounts = [
        initial_pool_balances[i] * lp_to_remove // initial_total_supply for i in range(N_COINS)
    ]

    actual_withdrawn_amounts = pool.remove_liquidity(
        lp_to_remove, min_amounts_to_receive, bob, sender=user_account
    )

    for i in range(N_COINS):
        assert actual_withdrawn_amounts[i] == expected_withdraw_amounts[i]

    # Verify event was emitted
    event_collection = pool.get_logs()
    remove_liquidity_event = None
    for e in event_collection:
        if "RemoveLiquidity" in str(e):
            remove_liquidity_event = e
            break
    assert remove_liquidity_event is not None, "RemoveLiquidity event not found"

    assert remove_liquidity_event.provider == user_account

    assert pool.balanceOf(user_account) == initial_lp_balance_user - lp_to_remove
    assert pool.totalSupply() == initial_total_supply - lp_to_remove

    final_pool_balances = [pool.balances(i) for i in range(N_COINS)]
    for i in range(N_COINS):
        assert final_pool_balances[i] == initial_pool_balances[i] - expected_withdraw_amounts[i]
        assert (
            coins[i].balanceOf(bob)
            == bob_coin_balances_before_action[i] + expected_withdraw_amounts[i]
        )
        assert coins[i].balanceOf(user_account) == user_coin_balances_before_remove[i]

    expected_d = initial_d - (initial_d * lp_to_remove // initial_total_supply)
    assert pool.D() == expected_d


@pytest.mark.parametrize("donation_present", [False, True])
def test_pool_reinitialization_after_full_user_withdrawal(pool, coins, bob, donation_present):
    user_account = boa.env.eoa
    second_provider_account = bob
    gm_pool = GodModePool(pool)

    # --- Initial User Liquidity ---
    lp_for_user = gm_pool.add_liquidity_balanced(amount=USER_LP_ADD_AMOUNT_COIN0)
    assert lp_for_user > 0, "User initial liquidity minting failed"
    initial_user_lp_balance = pool.balanceOf(user_account)
    assert initial_user_lp_balance == lp_for_user

    # --- Optional Donation ---
    donation_shares_value = 0
    if donation_present:
        gm_pool.donate_balanced(amount=DONATION_ADD_AMOUNT_COIN0)
        donation_shares_value = pool.donation_shares()
        assert (
            donation_shares_value > 0
        ), "Donation did not result in donation shares (logic for donation_present=True)"

    vp_before_main_ops = pool.virtual_price()
    xcp_profit_a_before_main_ops = pool.xcp_profit_a()

    # --- User withdraws ALL their LP tokens ---
    pool.remove_liquidity(initial_user_lp_balance, [0] * N_COINS, sender=user_account)
    assert pool.balanceOf(user_account) == 0, "User LP balance not zero after full withdrawal"

    # --- Assertions: Intermediate State (after user withdrawal, before Bob adds) ---
    current_total_supply_after_user_withdraw = pool.totalSupply()
    current_D_after_user_withdraw = pool.D()
    current_vp_after_user_withdraw = pool.virtual_price()
    current_xcp_profit_a_after_user_withdraw = pool.xcp_profit_a()
    balances_after_user_withdraw = [pool.balances(i) for i in range(N_COINS)]

    assert all(
        b == 0 for b in balances_after_user_withdraw
    ), f"Intermediate pool balances not all zero. Balances: {balances_after_user_withdraw}. Expected [0,0]."
    assert (
        current_D_after_user_withdraw == 0
    ), f"Intermediate D not zero. D: {current_D_after_user_withdraw}. Expected 0."

    assert (
        current_total_supply_after_user_withdraw == 0
    ), f"Intermediate total supply not zero. Expected 0, got {current_total_supply_after_user_withdraw}"

    # VP and XCP_A retain values from before this specific user withdrawal
    assert (
        current_vp_after_user_withdraw == vp_before_main_ops
    ), f"VP changed unexpectedly post-withdrawal. Expected {vp_before_main_ops}, got {current_vp_after_user_withdraw}."
    assert (
        current_xcp_profit_a_after_user_withdraw == xcp_profit_a_before_main_ops
    ), f"XCP_A changed unexpectedly post-withdrawal. Expected {xcp_profit_a_before_main_ops}, got {current_xcp_profit_a_after_user_withdraw}."

    # --- Action 2: Second provider (Bob) adds new liquidity ---
    bob_adds_amounts = gm_pool.compute_balanced_amounts(SECOND_USER_ADD_AMOUNT_COIN0)
    for i in range(N_COINS):
        coins[i].approve(pool.address, bob_adds_amounts[i], sender=second_provider_account)
        if coins[i].balanceOf(second_provider_account) < bob_adds_amounts[i]:
            boa.deal(
                coins[i],
                second_provider_account,
                bob_adds_amounts[i] - coins[i].balanceOf(second_provider_account),
            )

    pool.add_liquidity(bob_adds_amounts, 0, sender=second_provider_account)

    # --- Assertions: Final State (after Bob adds liquidity) ---
    vp_after_bob_add = pool.virtual_price()
    xcp_profit_a_after_bob_add = pool.xcp_profit_a()

    assert (
        vp_after_bob_add == PRECISION
    ), "Pool VP not reinitialized to PRECISION after Bob's deposit."
    assert (
        xcp_profit_a_after_bob_add == PRECISION
    ), "Pool XCP_A not reinitialized to PRECISION after Bob's deposit."
    assert pool.D() > 0, "Pool D is not > 0 after Bob's deposit."
    assert pool.totalSupply() > 0, "Pool totalSupply is not > 0 after Bob's deposit."


@pytest.mark.parametrize("i", range(N_COINS))
def test_no_fee_discount_with_remove_liquidity(pool, i):
    pool = GodModePool(pool)

    print("======= seeding liquidity")
    initial_liquidity = 1_000_000 * PRECISION
    initial_liquidity = np.array(pool.compute_balanced_amounts(initial_liquidity))
    pool.add_liquidity(initial_liquidity.tolist())

    print("======= swap")
    # we imbalance the pool because without updating the tweak price not
    # to trigger rebalances. It is the divergence between price scale and
    # spot price that creates the fee discount.
    pool.exchange(i, int(0.45 * initial_liquidity[i]))

    ps_balanced_amounts = pool.compute_balanced_amounts(int(initial_liquidity[i] * 0.5))
    with boa.env.anchor():
        print("====== add+remove liquidity")
        lp_tokens = pool.add_liquidity(ps_balanced_amounts)
        spot_balanced_amounts = pool.remove_liquidity(lp_tokens, [0, 0])

    ps_balanced_np = np.array(ps_balanced_amounts)
    spot_balanced_np = np.array(spot_balanced_amounts)
    delta = spot_balanced_np - ps_balanced_np
    print(f"Balances delta: {delta / PRECISION}")

    swapped_amount = abs(min(delta))
    print(
        f"This is equivalent to swapping (i) {swapped_amount/PRECISION:.5f} -> (j) {max(delta)/PRECISION:.5f}"
    )

    with boa.env.anchor():
        print("======= check swap")
        # index of swapped_amount in delta
        i = int(np.where(delta == min(delta))[0][0])
        out_amount = pool.exchange(i, swapped_amount)
    print(
        f"            Actual swap led to (i) {swapped_amount/PRECISION:.5f} -> (j) {out_amount/PRECISION:.5f}"
    )

    assert out_amount >= delta[1 - i], "add+remove is getting a discount on fees"
