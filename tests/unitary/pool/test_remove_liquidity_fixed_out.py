import boa


def test_remove_liquidity_fixed_out_both_coins(swap_with_deposit, coins, user):
    total_supply = swap_with_deposit.totalSupply()
    token_amount = total_supply // 10  # 10% of total supply

    # Test with each coin as the fixed coin
    for i in range(len(coins)):
        j = 1 - i

        # Get initial state
        initial_balances = [swap_with_deposit.balances(k) for k in range(len(coins))]
        expected = [balance * token_amount // total_supply for balance in initial_balances]

        # Use 50% of the expected amount for the fixed coin
        amount_i = expected[i] // 2

        # Get user balances before withdrawal
        user_balances_before = [c.balanceOf(user) for c in coins]

        # Execute the remove_liquidity_fixed_out function
        with boa.env.prank(user):
            dy = swap_with_deposit.remove_liquidity_fixed_out(
                token_amount,
                i,
                amount_i,
                0,  # No minimum
            )

        # Get user balances after withdrawal
        user_balances_after = [c.balanceOf(user) for c in coins]

        # Calculate actual changes
        withdrawn = [user_balances_after[k] - user_balances_before[k] for k in range(len(coins))]

        # Verify the fixed amount of token i was withdrawn
        assert withdrawn[i] == amount_i

        # Verify the returned amount of token j matches what was actually withdrawn
        assert withdrawn[j] == dy

        # Verify the pool is still functional
        swap_with_deposit.get_dy(0, 1, 10**16)


def test_remove_liquidity_fixed_out_slippage(swap_with_deposit, coins, user):
    total_supply = swap_with_deposit.totalSupply()
    token_amount = total_supply // 10  # 10% of total supply

    i = 0

    # Get initial state
    initial_balances = [swap_with_deposit.balances(k) for k in range(len(coins))]
    expected = [balance * token_amount // total_supply for balance in initial_balances]

    # Use 50% of the expected amount for token i
    amount_i = expected[i] // 2

    # First, get the actual dy that would be returned with min_amount_j = 0
    with boa.env.prank(user):
        dy = swap_with_deposit.remove_liquidity_fixed_out(
            token_amount,
            i,
            amount_i,
            0,  # No minimum to get the actual amount
        )

    # Reset the state
    boa.env.time_travel(seconds=1)

    # Test with a min_amount_j that's too high (should revert with "slippage")
    with boa.env.prank(user):
        with boa.reverts("slippage"):
            swap_with_deposit.remove_liquidity_fixed_out(
                token_amount,
                i,
                amount_i,
                dy + 1,  # Just slightly more than possible
            )


def test_remove_liquidity_fixed_out_max_token_amount(swap_with_deposit, coins, user):
    total_supply = swap_with_deposit.totalSupply()

    # Get initial state
    initial_balances = [swap_with_deposit.balances(i) for i in range(len(coins))]

    i = 0

    # Use slightly less than the full balance for token i
    amount_i = initial_balances[i] - 1

    # Execute the remove_liquidity_fixed_out function with more than the total supply
    with boa.env.prank(user):
        with boa.reverts("withdraw > supply"):
            swap_with_deposit.remove_liquidity_fixed_out(
                total_supply + 1,  # More than total supply
                i,
                amount_i,
                0,
            )


def test_remove_liquidity_fixed_out_excessive_amount(swap_with_deposit, coins, user):
    total_supply = swap_with_deposit.totalSupply()
    token_amount = total_supply // 2  # 50% of total supply

    i = 0

    # Get initial state
    initial_balances = [swap_with_deposit.balances(i) for i in range(len(coins))]

    # Try to withdraw more than the pool has of token i
    amount_i = initial_balances[i] + 1

    # This should fail because we're trying to withdraw more than the pool has
    with boa.env.prank(user):
        # The error is a safesub error (subtraction underflow)
        with boa.reverts("safesub"):
            swap_with_deposit.remove_liquidity_fixed_out(
                token_amount,
                i,
                amount_i,
                0,
            )


def test_remove_liquidity_fixed_out_invalid_coin_index(swap_with_deposit, coins, user):
    total_supply = swap_with_deposit.totalSupply()
    token_amount = total_supply // 10  # 10% of total supply

    # Use an out-of-range coin index
    i = 2  # This is invalid since N_COINS = 2 (valid indices are 0 and 1)

    # Use a reasonable amount for token i
    amount_i = 10**18  # 1 token

    # This should fail due to underflow in j = 1 - i calculation
    with boa.env.prank(user):
        with boa.reverts("safesub"):
            swap_with_deposit.remove_liquidity_fixed_out(
                token_amount,
                i,
                amount_i,
                0,
            )
