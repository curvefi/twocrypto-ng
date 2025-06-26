from tests.utils.god_mode import GodModePool
from tests.utils.constants import N_COINS, NOISE_FEE
import pytest
import boa

INITIAL_LIQUIDITY = 1000 * 10**18


@pytest.fixture(scope="module")
def user_account():
    return boa.env.generate_address()


@pytest.fixture(scope="module")
def bob():
    return boa.env.generate_address()


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


def test_calc_token_fee_view_donation_protection(pool, user_account, bob):
    gm_pool = GodModePool(pool)
    # 1. user_account adds initial liquidity. This seeds the pool.
    user_adds_amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY // 20)
    gm_pool.premint_amounts(user_adds_amounts, to=user_account)
    pool.add_liquidity(user_adds_amounts, 0, sender=user_account)
    assert pool.donation_protection_expiry_ts() == 0

    # 2. bob adds liquidity right after
    bob_adds_amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY)
    gm_pool.premint_amounts(bob_adds_amounts, to=bob)
    pool.add_liquidity(bob_adds_amounts, 0, sender=bob)
    # still 0, we have no donations in pool
    assert pool.donation_protection_expiry_ts() == 0

    # donate. Now donation shares are nonzero
    gm_pool.donate(bob_adds_amounts, 0)

    # 2a. bob adds liquidity right after, triggering protection.
    bob_adds_amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY)
    gm_pool.premint_amounts(bob_adds_amounts, to=bob)
    pool.add_liquidity(bob_adds_amounts, 0, sender=bob)
    # still 0, we have no donations in pool
    assert pool.donation_protection_expiry_ts() > boa.env.evm.patch.timestamp

    # 3. charlie is our test case. Prepare his deposit details.
    charlie_adds_amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY // 10)
    # 4. Get the initial fee right after protection is triggered. It should be high.
    last_fee = pool.calc_token_fee(charlie_adds_amounts, gm_pool.xp(), False, True)
    assert last_fee > 0

    # 5. Loop through time and assert the fee decreases.
    protection_period = pool.donation_protection_period()
    steps = 10
    time_step = protection_period // steps

    for _ in range(steps - 1):
        boa.env.time_travel(seconds=time_step)
        current_fee = pool.calc_token_fee(charlie_adds_amounts, gm_pool.xp(), False, True)
        assert current_fee < last_fee
        last_fee = current_fee

    # 6. Travel past the protection period.
    boa.env.time_travel(seconds=time_step + 1)

    # 7. Check the fee is now the base fee.
    final_fee = pool.calc_token_fee(charlie_adds_amounts, gm_pool.xp(), False, True)
    base_fee = pool.calc_token_fee(charlie_adds_amounts, gm_pool.xp(), False, False)
    assert final_fee == pytest.approx(base_fee)
    assert final_fee < last_fee
