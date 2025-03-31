import boa
import pytest


# @pytest.mark.xfail
@pytest.mark.parametrize(
    "fee_gamma",
    [10**4, 10**8, 10**12, 10**16],  # Low, medium, high fee_gamma values
)
@pytest.mark.parametrize(
    "initial_balance_rate",
    [0.1, 0.3, 0.5],  # Different rates of pool balance
)
def test_round_trip_swaps(pool_with_deposit, coins, user, fee_gamma, initial_balance_rate, params):
    """
    Test that swaps back and forth between token0 and token1 result in
    only losing the fee amount of token0.

    We start with a balanced pool and a user with lots of coin0.
    The test is parametrized with different fee_gamma values and
    initial balance rates (as a percentage of pool balance).

    The test always uses the entire balance of coins the user has for each swap.
    """
    # Set fee_gamma parameter
    with boa.env.prank(pool_with_deposit.admin()):
        pool_with_deposit.apply_new_parameters(
            params["mid_fee"],
            params["out_fee"],
            fee_gamma,
            params["allowed_extra_profit"],
            params["adjustment_step"],
            params["ma_time"],
        )

    # Get initial pool balances
    initial_pool_balance_0 = pool_with_deposit.balances(0)

    # get initial user balances

    assert coins[0].balanceOf(user) == 0
    assert coins[1].balanceOf(user) == 0

    # Calculate initial swap amount based on pool balance rate
    initial_user_balance = int(initial_pool_balance_0 * initial_balance_rate)

    # Mint tokens for the user
    boa.deal(coins[0], user, initial_user_balance)
    assert coins[0].balanceOf(user) == initial_user_balance

    # Approve the swap contract to use the tokens
    with boa.env.prank(user):
        coins[0].approve(pool_with_deposit.address, 2**256 - 1)
        coins[1].approve(pool_with_deposit.address, 2**256 - 1)

    # Number of round trips to perform
    num_round_trips = 1

    # count swap volume (in token 0) to calculate fees
    swap_volume = 0
    # Perform repeated round-trip swaps
    for i in range(num_round_trips):
        # Swap all token0 -> token1
        with boa.env.prank(user):
            swap_volume += coins[0].balanceOf(user)  # add before swap
            pool_with_deposit.exchange(0, 1, coins[0].balanceOf(user), 0)
            assert coins[0].balanceOf(user) == 0
        # Swap all token1 -> token0
        with boa.env.prank(user):
            pool_with_deposit.exchange(1, 0, coins[1].balanceOf(user), 0)
            assert coins[1].balanceOf(user) == 0
            swap_volume += coins[0].balanceOf(
                user
            )  # add after swap (imprecise, because fee already taken)
    # Calculate how much token0 was lost due to fees
    final_user_balance_0 = coins[0].balanceOf(user)
    token0_lost = initial_user_balance - final_user_balance_0
    token0_lost_percentage = token0_lost * 10_000 // initial_user_balance  # in basis points

    # Assert that token0 lost is reasonable
    # We have 2 * num_round_trips swaps in total
    total_swaps = 2 * num_round_trips

    # The out_fee is in units of 10^-10, so we need to convert it to basis points (10^-4)
    out_fee_bps = params["out_fee"] // 10**6  # Convert from 10^-10 to basis points (10^-4)

    # Calculate maximum expected fee (upper bound)
    max_expected_fee_bps = out_fee_bps * total_swaps  # Convert back to basis points

    assert (
        token0_lost_percentage <= max_expected_fee_bps
    ), f"Token0 lost ({token0_lost_percentage} bps) exceeds max expected fee ({max_expected_fee_bps} bps)"
