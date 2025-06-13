from tests.utils.god_mode import GodModePool
from tests.utils.constants import N_COINS, NOISE_FEE
import pytest


@pytest.mark.parametrize("i", range(N_COINS))
def test_fee_increases_with_spot_imbalance(pool, i):
    pool: GodModePool = GodModePool(pool)

    # Add balanced liquidity
    pool.add_liquidity_balanced(100_000_000 * 10**18)

    # Perform exchange to unbalance the pool
    pool.exchange(i, 10_000_000 * 10**18)

    # Get current balances
    balances = pool.balances()

    # Test with increasing imbalance percentages
    previous_fee = 0

    # Test imbalance from 0% (perfectly balanced) to 50% (highly imbalanced)
    for imbalance_percent in range(0, 49, 5):
        imbalance_factor = imbalance_percent / 100.0

        if i == 0:
            # Withdraw more of coin 0
            amounts = [
                int(balances[0] * (0.5 + imbalance_factor)),
                int(balances[1] * (0.5 - imbalance_factor)),
            ]
        else:
            # Withdraw more of coin 1
            amounts = [
                int(balances[0] * (0.5 - imbalance_factor)),
                int(balances[1] * (0.5 + imbalance_factor)),
            ]

        # Ensure we're not trying to withdraw more than available
        amounts = [min(amounts[j], balances[j]) for j in range(N_COINS)]

        # Calculate fee for this imbalance level
        current_fee = pool.calc_token_fee(amounts, balances, False)

        # For perfect balance (0% imbalance), fee should be NOISE_FEE
        if imbalance_percent == 0:
            assert current_fee == NOISE_FEE, "Balanced withdrawal fee should be NOISE_FEE"
        # For any other imbalance, fee should be strictly increasing
        elif imbalance_percent > 0:
            assert (
                current_fee > previous_fee
            ), f"Fee at {imbalance_percent}% imbalance should be higher than at {imbalance_percent-5}%"

        previous_fee = current_fee


def test_donation_mode(pool):
    pool: GodModePool = GodModePool(pool)
    pool.add_liquidity_balanced(100_000_000 * 10**18)

    assert NOISE_FEE == pool.calc_token_fee(
        [1, 1],
        [1, 1],
        True,
    )
