"""
Test suite for stableswap math implementations, comparing both Stableswap and Twocrypto
math contract behaviors with precise decimal handling.
"""

import pytest
import boa
from decimal import Decimal, getcontext
from dataclasses import dataclass
from typing import List

# Set precision
getcontext().prec = 78


@dataclass
class PoolParams:
    """Pool parameters configuration"""

    A: int = 400000
    gamma: int = 145000000000000
    mid_fee: int = 26000000
    out_fee: int = 45000000
    fee_gamma: int = 230000000000000
    allowed_extra_profit: int = 2000000000000
    adjustment_step: int = 146000000000000
    ma_exp_time: int = 866
    name: str = "crypto"
    description: str = "frontend preset for volatile assets"


class StableswapTestCase:
    """Test case implementation for stableswap calculations"""

    def __init__(self, math_contract, contract_name: str):
        self.math_contract = math_contract
        self.contract_name = contract_name
        self.scale = Decimal(10**18)  # Decimal scaling factor
        self.params = PoolParams()

    def _to_decimal(self, value: int) -> Decimal:
        """Convert integer to decimal with proper scaling"""
        return Decimal(value) / self.scale

    def _to_int(self, value: Decimal) -> int:
        """Convert decimal to integer with proper scaling"""
        return int(value * self.scale)

    def _format_balances(self, balances: List[int]) -> str:
        """Format balances list for readable output"""
        return f"[{self._to_decimal(balances[0]):.2f}, {self._to_decimal(balances[1]):.2f}]"


@pytest.fixture(scope="module")
def stableswap_math(deployer):
    """Deploy StableswapMath contract"""
    with boa.env.prank(deployer):
        return boa.load_partial("contracts/main/StableswapMath.vy").deploy()


@pytest.fixture(scope="module")
def twocrypto_math(deployer):
    """Deploy TwocryptoMath contract"""
    with boa.env.prank(deployer):
        return boa.load_partial("contracts/main/TwocryptoMath.vy").deploy()


def run_get_y_test(test_case: StableswapTestCase):
    """
    Core test logic for get_y function with precise decimal calculations
    """
    # Initialize pool state with integer values
    init_balance_decimal = Decimal("1_000_000")
    init_balance = test_case._to_int(init_balance_decimal)
    xp = [init_balance, init_balance]
    user_balance = [init_balance * 10, 0]  # Only token0 balance initially
    init_user_balance = user_balance.copy()  # Store initial balances for both tokens

    # Configuration
    fee_percentage = Decimal("0.005")  # 0.5% fee
    n_swaps = 2  # Must be even to return to original token
    assert n_swaps % 2 == 0, "Number of swaps must be even"
    fees_collected = [0, 0]  # Track fees in integer form

    # Calculate initial D (returns integer)
    D = test_case.math_contract.newton_D(test_case.params.A, test_case.params.gamma, xp)

    print(f"\n=== Testing {test_case.contract_name} ===")
    print("\nInitial State:")
    print(f"Pool balances: {test_case._format_balances(xp)}")
    print(f"Initial D: {test_case._to_decimal(D):.2f}")
    print(f"Initial user balances: {test_case._format_balances(user_balance)}")

    print(f"\nExecuting {n_swaps} swaps with {fee_percentage * 100}% fee rate")

    for swap_num in range(n_swaps):
        # Alternate between token0->token1 and token1->token0
        i = swap_num % 2  # 0,1,0,1,...
        j = 1 - i  # 1,0,1,0,...
        amount = user_balance[i]  # Integer amount

        print(f"\nSwap {swap_num + 1}:")
        print(f"Direction: token{i} -> token{j}")
        print(f"Amount: {test_case._to_decimal(amount):.2f}")
        print(f"User balances before: {test_case._format_balances(user_balance)}")
        print(f"Pool balances before: {test_case._format_balances(xp)}")

        # Execute swap (all values are integers)
        user_balance[i] -= amount
        xp[i] += amount
        new_y = test_case.math_contract.get_y(test_case.params.A, test_case.params.gamma, xp, D, j)

        # Calculate output and fees (convert to decimal only for fee calculation)
        dy = xp[j] - new_y[0]  # Integer subtraction
        fee_amount = test_case._to_int(test_case._to_decimal(dy) * fee_percentage)

        # Update balances (all integer operations)
        fees_collected[j] += fee_amount
        dy_after_fee = dy - fee_amount
        xp[j] = new_y[0] + fee_amount
        user_balance[j] += dy_after_fee

        # Update D (returns integer)
        D = test_case.math_contract.newton_D(test_case.params.A, test_case.params.gamma, xp)

        print(f"User balances after: {test_case._format_balances(user_balance)}")
        print(f"Pool balances after: {test_case._format_balances(xp)}")
        print(f"Fee collected on token{j}: {test_case._to_decimal(fee_amount):.4f}")

    # Assertions and final reporting
    assert user_balance[1] == 0, "Token1 balance must be zero after swap chain"

    # Calculate final values (maintain integer precision until display)
    true_fees = sum(fees_collected)  # Sum of actual fees collected during swaps

    # Calculate perceived fees from balance changes
    balance_changes = [user_balance[k] - init_user_balance[k] for k in range(2)]
    # Initial token0 amount was swapped completely, so perceived fee is the "loss" in value
    perceived_fees = -balance_changes[0]  # Always use token0 since we start and end with it

    print("\nFinal Results:")
    print(f"Final pool balances: {test_case._format_balances(xp)}")
    print(f"Final D: {test_case._to_decimal(D):.2f}")
    print("\nUser Balance Summary:")
    print(f"Initial balances: {test_case._format_balances(init_user_balance)}")
    print(f"Final balances: {test_case._format_balances(user_balance)}")
    print(f"Balance changes: {test_case._format_balances(balance_changes)}")
    print("\nFees Summary:")
    print(f"Fees collected per token: {test_case._format_balances(fees_collected)}")
    print(f"True fees (collected): {test_case._to_decimal(true_fees):.4f}")
    print(f"Perceived fees (from balance change): {test_case._to_decimal(perceived_fees):.4f}")

    # Calculate and display user balance changes (convert to decimal only for display)
    print("\nUser Balance Changes:")
    for k in range(2):
        print(f"Token{k}:")
        print(f"  Absolute change: {test_case._to_decimal(balance_changes[k]):.2f}")
        if init_user_balance[k] != 0:
            pct_change = test_case._to_decimal(balance_changes[k]) / test_case._to_decimal(
                init_user_balance[k]
            )
            print(f"  Percentage change: {pct_change:.2%}")

    # Calculate theoretical upper bound on fees
    upper_bound_fees = test_case._to_int(
        test_case._to_decimal(init_user_balance[0]) * fee_percentage * n_swaps
    )
    return true_fees, perceived_fees, upper_bound_fees


@pytest.mark.xfail
def test_get_y_stableswap(stableswap_math):
    """Test get_y function for StableswapMath implementation"""
    test_case = StableswapTestCase(stableswap_math, "StableswapMath")
    true_fees, perceived_fees, upper_bound_fees = run_get_y_test(test_case)

    # relaxed check on upper bound (plus numerical errors)
    assert (
        perceived_fees <= 1.001 * upper_bound_fees
    ), "StableswapMath: Collected fees exceed maximum expected"

    # very strict check, always fails
    assert true_fees == perceived_fees, "StableswapMath: True fees differ from perceived fees"


@pytest.mark.xfail
def test_get_y_twocrypto(twocrypto_math):
    """Test get_y function for TwocryptoMath implementation"""
    test_case = StableswapTestCase(twocrypto_math, "TwocryptoMath")
    true_fees, perceived_fees, upper_bound_fees = run_get_y_test(test_case)

    # relaxed check on upper bound (plus numerical errors)
    assert (
        perceived_fees <= 1.001 * upper_bound_fees
    ), "TwocryptoMath: Collected fees exceed maximum expected"

    # very strict check, always fails
    assert true_fees == perceived_fees, "TwocryptoMath: True fees differ from perceived fees"
