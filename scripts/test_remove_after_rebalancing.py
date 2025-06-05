import sys
import os

# Add project root to sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import boa
from tests.utils.helper import deploy_test_pool

# ============================================================================
# Pool Setup
# ============================================================================

factory = boa.load_partial("contracts/main/TwocryptoFactory.vy")
print("\n--- Pool Setup ---")
gm_pool = deploy_test_pool(initial_price=20 * 10**18)

# Initial liquidity provision
initial_amount = 400_000 * 10**18
gm_pool.add_liquidity_balanced(initial_amount, donate=False)
print(f"Initial D: {gm_pool.D() // 10**18:,}")

# ============================================================================
# Phase 1: Donation
# ============================================================================

donation_amount = 200_000 * 10**18
lp_from_donation = gm_pool.donate_balanced(donation_amount)
print(f"Donated {donation_amount // 10**18:,}, received LP: {lp_from_donation // 10**18:,}")

# ============================================================================
# Phase 2: Unbalance the Pool
# ============================================================================

print("\n--- Unbalancing the pool ---")
exchange_amount = 200_000 * 10**18
tokens_out = gm_pool.exchange(0, exchange_amount)
print(f"Exchanged {exchange_amount // 10**18:,} coin0, received {tokens_out // 10**18:,} coin1")

current_balances = [gm_pool.balances(0), gm_pool.balances(1)]
print(f"Pool balances: [{current_balances[0] // 10**18:,}, {current_balances[1] // 10**18:,}]")

# ============================================================================
# Phase 3: Manipulate Oracle and Time Travel
# ============================================================================

new_oracle_price = 24 * 10**18
gm_pool.set_price_oracle(new_oracle_price)
print(f"Set price oracle to: {gm_pool.price_oracle() // 10**18}")

# Time travel 1 week to allow oracle update
week_in_seconds = 86400 * 7
boa.env.time_travel(seconds=week_in_seconds)
print("Time traveled 1 week")

# ============================================================================
# Phase 4: Add Liquidity (Trigger Rebalancing)
# ============================================================================

print("\n--- Adding Liquidity (Balanced) ---")
liquidity_amount = 500_000 * 10**18
balances = [gm_pool.balances(0), gm_pool.balances(1)]
fraction = liquidity_amount / balances[0]
balanced_amounts = [int(balances[0] * fraction), int(balances[1] * fraction)]

lp_tokens_received = gm_pool.add_liquidity(balanced_amounts, donate=False)
print(
    f"Added balanced liquidity: [{balanced_amounts[0] // 10**18:,}, {balanced_amounts[1] // 10**18:,}]"
)
print(f"Received LP tokens: {lp_tokens_received // 10**18:,}")

# ============================================================================
# Phase 5: Remove Liquidity and Calculate Delta
# ============================================================================

print("\n--- Removing Liquidity (Balanced) ---")
assets_received = gm_pool.remove_liquidity(lp_tokens_received, [0, 0])

# Calculate the net gain/loss
delta_coin0 = assets_received[0] - balanced_amounts[0]
delta_coin1 = assets_received[1] - balanced_amounts[1]

print(f"Assets received: [{assets_received[0] // 10**18:,}, {assets_received[1] // 10**18:,}]")
print(f"Net delta coin0: {delta_coin0 // 10**18:,}")
print(f"Net delta coin1: {delta_coin1 // 10**18:,}")

if delta_coin0 > 0 or delta_coin1 > 0:
    print("✅ Net positive return detected")
else:
    print("❌ Net loss or break-even")
