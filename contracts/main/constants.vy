N_COINS: constant(uint256) = 2
WAD: constant(uint256) = 10**18

# A and gamma
MIN_GAMMA: constant(uint256) = 10**10
MAX_GAMMA_SMALL: constant(uint256) = 2 * 10**16
MAX_GAMMA: constant(uint256) = 199 * 10**15 # 1.99 * 10**17

A_MULTIPLIER: constant(uint256) = 10000
MIN_A: constant(uint256) = N_COINS**N_COINS * A_MULTIPLIER // 10
MAX_A: constant(uint256) = N_COINS**N_COINS * A_MULTIPLIER * 1000

# Ramping constants
MIN_RAMP_TIME: constant(uint256) = 86400
MAX_A_CHANGE: constant(uint256) = 10
MAX_GAMMA_CHANGE: constant(uint256) = 10

# Fee constants
ADMIN_FEE: public(constant(uint256)) = 5 * 10**9  # 50% of the fee
MIN_FEE: constant(uint256) = 5 * 10**5  # 0.5 BPS.
MAX_FEE: constant(uint256) = 10**10
# TODO explain where this is used and why
NOISE_FEE: constant(uint256) = 10**5  # 0.1 BPS.
