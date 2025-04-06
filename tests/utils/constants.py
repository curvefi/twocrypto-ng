"""
Constants often used for testing.

These cannot be used as fixtures because they are often
used as bounds for fuzzing (outside of the test functions).

This file also makes sure that constants with the same name
are consistent across different contracts.
"""

import boa

c = boa.load_partial("contracts/helpers/constants.vy")

N_COINS = c._constants.N_COINS
MIN_GAMMA = c._constants.MIN_GAMMA
MAX_GAMMA = c._constants.MAX_GAMMA
MAX_GAMMA_SMALL = c._constants.MAX_GAMMA_SMALL
A_MULTIPLIER = c._constants.A_MULTIPLIER
MIN_A = c._constants.MIN_A
MAX_A = c._constants.MAX_A
UNIX_DAY = 86400
MIN_FEE = c._constants.MIN_FEE
MAX_FEE = c._constants.MAX_FEE
MIN_RAMP_TIME = c._constants.MIN_RAMP_TIME
