N_COINS: constant(uint256) = 2
WAD: constant(uint256) = 10**18
MIN_RAMP_TIME: constant(uint256) = 86400

MIN_ADMIN_FEE_CLAIM_INTERVAL: constant(uint256) = 86400
A_MULTIPLIER: constant(uint256) = 10000
MIN_A: constant(uint256) = N_COINS**N_COINS * A_MULTIPLIER // 10
MAX_A: constant(uint256) = N_COINS**N_COINS * A_MULTIPLIER * 1000
MAX_A_CHANGE: constant(uint256) = 10
MIN_GAMMA: constant(uint256) = 10**10
MAX_GAMMA: constant(uint256) = 199 * 10**15 # 1.99 * 10**17
MIN_FEE: constant(uint256) = 5 * 10**5
MAX_FEE: constant(uint256) = 10 * 10**9
MAX_GAMMA_SMALL: constant(uint256) = 2 * 10**16
