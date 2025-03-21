"""
Constants often used for testing.

These cannot be used as fixtures because they are often
used as bounds for fuzzing (outside of the test functions).

This file also makes sure that constants with the same name
are consistent across different contracts.
"""

import boa

MATH_DEPLOYER = boa.load_partial("contracts/main/TwocryptoMath.vy")
VIEW_DEPLOYER = boa.load_partial("contracts/main/TwocryptoView.vy")
FACTORY_DEPLOYER = boa.load_partial("contracts/main/TwocryptoFactory.vy")
POOL_DEPLOYER = boa.load_partial("contracts/main/Twocrypto.vy")
GAUGE_DEPLOYER = boa.load_partial("contracts/main/LiquidityGauge.vy")
ERC20_DEPLOYER = boa.load_partial("tests/mocks/ERC20Mock.vy")

assert (
    POOL_DEPLOYER._constants.N_COINS
    == MATH_DEPLOYER._constants.N_COINS
    == FACTORY_DEPLOYER._constants.N_COINS
    == VIEW_DEPLOYER._constants.N_COINS
), "N_COINS mismatch"

N_COINS = POOL_DEPLOYER._constants.N_COINS

assert (
    POOL_DEPLOYER._constants.MIN_GAMMA == MATH_DEPLOYER._constants.MIN_GAMMA
), "MIN_GAMMA mismatch"

MIN_GAMMA = POOL_DEPLOYER._constants.MIN_GAMMA

assert (
    POOL_DEPLOYER._constants.MAX_GAMMA == MATH_DEPLOYER._constants.MAX_GAMMA
), "MAX_GAMMA mismatch"

MAX_GAMMA = POOL_DEPLOYER._constants.MAX_GAMMA

MAX_GAMMA_SMALL = MATH_DEPLOYER._constants.MAX_GAMMA_SMALL

assert (
    POOL_DEPLOYER._constants.A_MULTIPLIER
    == MATH_DEPLOYER._constants.A_MULTIPLIER
    == FACTORY_DEPLOYER._constants.A_MULTIPLIER
), "A_MULTIPLIER mismatch"

A_MULTIPLIER = POOL_DEPLOYER._constants.A_MULTIPLIER

assert POOL_DEPLOYER._constants.MIN_A == MATH_DEPLOYER._constants.MIN_A, "MIN_A mismatch"

MIN_A = POOL_DEPLOYER._constants.MIN_A

assert POOL_DEPLOYER._constants.MAX_A == MATH_DEPLOYER._constants.MAX_A, "MAX_A mismatch"

MAX_A = POOL_DEPLOYER._constants.MAX_A

UNIX_DAY = 86400

MIN_FEE = POOL_DEPLOYER._constants.MIN_FEE

assert POOL_DEPLOYER._constants.MAX_FEE == FACTORY_DEPLOYER._constants.MAX_FEE, "MAX_FEE mismatch"

MAX_FEE = POOL_DEPLOYER._constants.MAX_FEE

MIN_RAMP_TIME = POOL_DEPLOYER._constants.MIN_RAMP_TIME
