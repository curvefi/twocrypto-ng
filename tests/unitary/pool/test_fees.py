import boa
import pytest
import math
from decimal import Decimal
from tests.utils.tokens import mint_for_testing
from tests.fixtures.pool import INITIAL_PRICES

# @pytest.mark.gas_profile
@pytest.mark.parametrize(
    "fee_gamma",
    [10 ** 4, 10 ** 8, 10 ** 12, 10 ** 16]  # Low, medium, high fee_gamma values
)
@pytest.mark.parametrize(
    "initial_balance_rate", [.1, .3, .5, 2, 5]  # Different rates of pool balance
)
def test_round_trip_swaps(swap_with_deposit, coins, user, fee_gamma, initial_balance_rate, params):
    """
    Test that swaps back and forth between token0 and token1 result in 
    only losing the fee amount of token0.
    
    We start with a balanced pool and a user with lots of coin0.
    The test is parametrized with different fee_gamma values and
    initial balance rates (as a percentage of pool balance).
    
    The test always uses the entire balance of coins the user has for each swap.
    """
    # Set fee_gamma parameter
    with boa.env.prank(swap_with_deposit.admin()):
        swap_with_deposit.apply_new_parameters(
            params["mid_fee"],
            params["out_fee"],
            fee_gamma,
            params["allowed_extra_profit"],
            params["adjustment_step"],
            params["ma_time"]
        )
    
    # Get initial pool balances
    initial_pool_balance_0 = swap_with_deposit.balances(0)
    initial_pool_balance_1 = swap_with_deposit.balances(1)
    
    # get initial user balances

    assert coins[0].balanceOf(user) == 0
    assert coins[1].balanceOf(user) == 0

    # Calculate initial swap amount based on pool balance rate
    initial_swap_amount = int(initial_pool_balance_0 * initial_balance_rate)
    
    print(f"\nTesting with fee_gamma={fee_gamma}, initial_balance_rate={initial_balance_rate}")
    
    # Mint tokens for the user
    mint_for_testing(coins[0], user, initial_swap_amount)
    assert coins[0].balanceOf(user) == initial_swap_amount

    # Approve the swap contract to use the tokens
    with boa.env.prank(user):
        coins[0].approve(swap_with_deposit.address, 2**256 - 1)
        coins[1].approve(swap_with_deposit.address, 2**256 - 1)  
    
    # Number of round trips to perform
    num_round_trips = 10
    
    # Perform repeated round-trip swaps
    for i in range(num_round_trips):
        
        # Swap all token0 -> token1
        with boa.env.prank(user):
            swap_with_deposit.exchange(0, 1, coins[0].balanceOf(user), 0)
            assert coins[0].balanceOf(user) == 0
        # Swap all token1 -> token0
        with boa.env.prank(user):
            swap_with_deposit.exchange(1, 0, coins[1].balanceOf(user), 0)
            assert coins[1].balanceOf(user) == 0
        
    # Calculate how much token0 was lost due to fees
    final_user_balance_0 = coins[0].balanceOf(user)
    token0_lost = initial_swap_amount - final_user_balance_0
    token0_lost_percentage = token0_lost * 10_000 // initial_swap_amount  # in basis points
    
    print(f"Token0 lost: {token0_lost_percentage} bps of initial amount)")
    
    # Assert that token0 lost is reasonable
    # We have 2 * num_round_trips swaps in total
    total_swaps = 2 * num_round_trips
    
    # The out_fee is in units of 10^-10, so we need to convert it to basis points (10^-4)
    out_fee_bps = params["out_fee"] // 10**6  # Convert from 10^-10 to basis points (10^-4)
    
    
    # Calculate maximum expected fee with compounding
    max_expected_fee_bps = out_fee_bps * total_swaps  # Convert back to basis points
    
    print(f"Max expected fee: {max_expected_fee_bps} bps")
    
    assert token0_lost_percentage <= max_expected_fee_bps, \
        f"Token0 lost ({token0_lost_percentage} bps) exceeds max expected fee ({max_expected_fee_bps} bps)"
    