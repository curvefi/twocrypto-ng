"""
This test suit containis basic tests to prevent regressions or breaking
changes in the math library. More in depth tests are done directly in the
snekmate repository.
"""

import random

params_dict = {
    "A": 400000,
    "gamma": 145000000000000,
    "mid_fee": 26000000,
    "out_fee": 45000000,
    "fee_gamma": 230000000000000,
    "allowed_extra_profit": 2000000000000,
    "adjustment_step": 146000000000000,
    "ma_exp_time": 866,
    "name": "crypto",
    "description": "frontend preset for volatile assets",
}


def test_get_y(math_contract):
    # Set a fixed seed for reproducible tests
    random.seed(42)

    scale = 10**18
    init_balance = 1000 * scale
    xp = [init_balance, init_balance]
    user_balance = [10 * init_balance, 0]

    # Fee configuration
    fee_percentage = 0.005  # 0.5% fee when enabled

    D = math_contract.newton_D(params_dict["A"], params_dict["gamma"], xp)
    # 1) swap 1x coin0 -> coin1
    print(f"Initial xp: [{xp[0]/scale:.2f}, {xp[1]/scale:.2f}], initial D: {D/scale:.2f}")
    failed = 0
    success = 0
    swap_size = 0
    total_fees_collected = [0, 0]
    N_SWAPS = 2
    for _ in range(N_SWAPS):
        try:  # avoid failures if pool is wildly imbalanced
            # Use the token the user has more of as the input token
            i = int(user_balance[1] >= user_balance[0])  # coin_in based on higher balance
            j = 1 - i
            amount = int(user_balance[i])  # * random.random())

            # if (_ == N_SWAPS-1) or (random.random() < 0.1 and xp[i] != init_balance):
            #     amount = min(init_balance - xp[i], user_balance[i])
            swap_size += amount
            print(
                f"Swap {_}, {i} -> {j}, size: {amount/scale:.2f}, "
                f"user_balance_before: [{user_balance[0]/scale:.2f}, {user_balance[1]/scale:.2f}], "
                f"pool_balance_before: [{xp[0]/scale:.2f}, {xp[1]/scale:.2f}]"
            )
            user_balance[i] -= amount
            xp[i] += amount
            new_y = math_contract.get_y(params_dict["A"], params_dict["gamma"], xp, D, j)

            # Calculate output amount before fees
            dy = xp[j] - new_y[0]

            fee_amount = 0
            # Apply fees if enabled
            if fee_percentage > 0:
                # Calculate fee amount
                fee_amount = int(dy * fee_percentage)
                total_fees_collected[j] += fee_amount

                # Calculate net amount out after fee
                dy_after_fee = dy - fee_amount

                # Update pool balances - leave the fee in the pool
                xp[j] = new_y[0] + fee_amount

                # Give user the amount after fees
                user_balance[j] += dy_after_fee
            else:
                # No fees - standard swap
                xp[j] = new_y[0]
                user_balance[j] += dy

            # Always show fee information in logs, even if it's zero
            print(
                f"user_balance_after: [{user_balance[0]/scale:.2f}, {user_balance[1]/scale:.2f}], "
                f"pool_balance_after: [{xp[0]/scale:.2f}, {xp[1]/scale:.2f}], "
                f"fee_collected: {fee_amount/scale:.4f}"
            )
            # update D
            D = math_contract.newton_D(params_dict["A"], params_dict["gamma"], xp)
            success += 1
        except Exception as e:
            failed += 1
            print(f"Error: {e}")
            continue
    # Balance out the pool after the swaps to initial state with single swap
    print(f"Success: {success}, Failed: {failed}, ratio: {success/(failed+success):.2f}")
    print(f"Final xp: [{xp[0]/scale:.2f}, {xp[1]/scale:.2f}], final D: {D/scale:.2f}")
    print(f"Avg swap size: {swap_size/N_SWAPS/scale:.2f}")
    print(
        f"Total fees collected: {sum(total_fees_collected)/scale:.4f}: "
        f"[{total_fees_collected[0]/scale:.4f}, {total_fees_collected[1]/scale:.4f}]"
    )
    fees_max_expected = fee_percentage * swap_size
    print(f"Fees max expected: {fees_max_expected/scale:.4f}")
    assert sum(total_fees_collected) <= fees_max_expected, "Fees collected exceed max expected"
