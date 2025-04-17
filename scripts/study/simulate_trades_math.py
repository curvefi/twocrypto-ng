#!/usr/bin/env python3
"""
This simulation script instantiates a pool via the Trader class and runs a loop of trades.
Script matches trading behavior from test_donation.py.
"""

import os
import sys
import time
import numpy as np
import matplotlib.pyplot as plt

# Add the absolute path of ../../tests to sys.path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from tests.utils.simulator import Trader

A = 400000
gamma = 145000000000000  # amplification coefficient parameters
D = 1_000_000 * 10**18  # total liquidity in the pool (adjust as needed)
p0 = [10**18, int(1500 * 10**18)]  # initial prices

# Fee settings (use decimal representations)
mid_fee = 0.0026  # mid fee as a decimal (0.26%)
out_fee = 0.0045  # out fee as a decimal (0.45%)
fee_gamma = 230000000000000  # fee gamma parameter
adjustment_step = 0.003  # adjustment step for price oracle updating
ma_time = 866  # moving average time parameter

# Instantiate the Trader simulation
trader = Trader(A, gamma, D, p0, mid_fee, out_fee, fee_gamma, adjustment_step, ma_time)

print("Initial pool state (raw balances):", trader.curve.x)
print("Initial pool state (scaled):", trader.curve.xp())
print("Initial constant pool value (D):", trader.curve.D())

# Number of trades in each direction
num_trades = 100
# Time between trades (7 days in seconds)
WEEK = 86400 * 7
data_array = []
t0 = time.perf_counter()

# ----- Match test_donation.py pattern -----
# First do N trades from token0 to token1
for i in range(num_trades):
    # Record current state data
    data_point = {
        "vp": trader.xcp,  # as close equivalent to virtual price as we can get
        "xcp_profit": trader.xcp_profit,
        "x": trader.curve.x.copy(),
        "p": trader.curve.p.copy(),
        "xp": trader.curve.xp(),
        "D": trader.curve.D(),
        "t": i * WEEK,
        "time": i * WEEK,
        "norm": 0,
    }
    data_array.append(data_point)

    # First half: swap token0 to token1
    # Use fixed size like in the test (10*2_000*10**18)
    dx = 10 * 2_000 * 10**18
    dy = trader.buy(dx, 0, 1)
    if dy is not False:
        print(f"Trade {i:03d}: Swapped {dx} token0 for {dy} token1")
    else:
        print(f"Trade {i:03d}: Swap failed")

    # Update the price oracle
    t = i * WEEK
    norm = trader.tweak_price(t)

# Then do N trades from token1 to token0
for i in range(num_trades):
    idx = i + num_trades
    # Record current state data
    data_point = {
        "vp": trader.xcp,  # as close equivalent to virtual price as we can get
        "xcp_profit": trader.xcp_profit,
        "x": trader.curve.x.copy(),
        "p": trader.curve.p.copy(),
        "xp": trader.curve.xp(),
        "D": trader.curve.D(),
        "t": idx * WEEK,
        "time": idx * WEEK,
        "norm": 0,
    }
    data_array.append(data_point)

    # Second half: swap token1 to token0
    # Use fixed size like in the test (5*10**18)
    dy = 5 * 10**18
    dx = trader.buy(dy, 1, 0)
    if dx is not False:
        print(f"Trade {idx:03d}: Swapped {dy} token1 for {dx} token0")
    else:
        print(f"Trade {idx:03d}: Swap failed")

    # Update the price oracle
    t = idx * WEEK
    norm = trader.tweak_price(t)

t1 = time.perf_counter()
print(f"Time taken: {t1 - t0} seconds")
print("Final pool state (raw balances):", trader.curve.x)
print("Final pool state (scaled):", trader.curve.xp())
print("Final constant pool value (D):", trader.curve.D())

#

# Extract data similar to test_donation.py
v_prices = (
    np.array([point["vp"] for point in data_array]) / 10**18 - 1
)  # Normalize like in test_donation
xcp_profit_values = np.array([point["xcp_profit"] for point in data_array]) / 10**18 - 1
t_values = np.array([point["time"] for point in data_array])

# Also extract the original data for additional plots
x_values = np.array([point["x"] for point in data_array]) / 10**18
xp_values = np.array([point["xp"] for point in data_array]) / 10**18
D_values = np.array([point["D"] for point in data_array]) / 10**18
p_values_all = np.array([point["p"] for point in data_array]) / 10**18

# Create subplots
fig, axs = plt.subplots(2, 2, figsize=(14, 10))

# Plot 1: Match the test_donation.py plot (virtual price and XCP profit)
axs[0, 0].plot(t_values, v_prices, label="Virtual price")
axs[0, 0].plot(t_values, xcp_profit_values, label="XCP profit")
axs[0, 0].plot(t_values, xcp_profit_values / 2, label="XCP profit/2", color="red", linestyle="--")
axs[0, 0].set_title("Virtual Price and XCP Profit")
axs[0, 0].set_xlabel("Time (seconds)")
axs[0, 0].set_ylabel("Value")
axs[0, 0].grid(True)
axs[0, 0].legend()

# Plot 2: Raw Balances
axs[0, 1].plot(t_values, x_values[:, 0], label="Token 0")
axs[0, 1].plot(t_values, x_values[:, 1], label="Token 1")
axs[0, 1].set_title("Raw Pool Balances")
axs[0, 1].set_xlabel("Time (seconds)")
axs[0, 1].set_ylabel("Balance")
axs[0, 1].grid(True)
axs[0, 1].legend()

# Plot 3: Scaled Balances
axs[1, 0].plot(t_values, xp_values[:, 0], label="Token 0")
axs[1, 0].plot(t_values, xp_values[:, 1], label="Token 1")
axs[1, 0].set_title("Scaled Pool Balances")
axs[1, 0].set_xlabel("Time (seconds)")
axs[1, 0].set_ylabel("Scaled Balance")
axs[1, 0].grid(True)
axs[1, 0].legend()

# Plot 4: Token Prices
axs[1, 1].plot(t_values, p_values_all[:, 0], label="Token 0 Price")
axs[1, 1].plot(t_values, p_values_all[:, 1], label="Token 1 Price")
axs[1, 1].set_title("Token Prices")
axs[1, 1].set_xlabel("Time (seconds)")
axs[1, 1].set_ylabel("Price")
axs[1, 1].grid(True)
axs[1, 1].legend()

plt.tight_layout()
plt.show()
