"""
Constants often used for testing.

These cannot be used as fixtures because they are often
used as bounds for fuzzing (outside of the test functions).

This file also makes sure that constants with the same name
are consistent across different contracts.
"""

import boa

# TODO move this to deployers.py
MATH_DEPLOYER = boa.load_partial("contracts/main/TwocryptoMath.vy")
VIEW_DEPLOYER = boa.load_partial("contracts/main/TwocryptoView.vy")
FACTORY_DEPLOYER = boa.load_partial("contracts/main/TwocryptoFactory.vy")
POOL_DEPLOYER = boa.load_partial("contracts/main/Twocrypto.vy")
GAUGE_DEPLOYER = boa.load_partial("contracts/main/LiquidityGauge.vy")
ERC20_DEPLOYER = boa.load_partial("tests/mocks/ERC20Mock.vy")

# TODO this should be tested from twocrypto directly
# temporary workaround till https://github.com/vyperlang/titanoboa/issues/393 is fixed
packing_utils = boa.load("contracts/main/packing_utils.vy")
# temporary workaround till https://github.com/vyperlang/titanoboa/issues/394 is fixed
PARAMS_DEPLOYER = boa.load_partial("contracts/main/params.vy")

# TODO use constants vyper module
N_COINS = POOL_DEPLOYER._constants.N_COINS
MIN_GAMMA = PARAMS_DEPLOYER._constants.MIN_GAMMA
MAX_GAMMA = PARAMS_DEPLOYER._constants.MAX_GAMMA
MAX_GAMMA_SMALL = MATH_DEPLOYER._constants.MAX_GAMMA_SMALL
A_MULTIPLIER = PARAMS_DEPLOYER._constants.A_MULTIPLIER
MIN_A = PARAMS_DEPLOYER._constants.MIN_A
MAX_A = PARAMS_DEPLOYER._constants.MAX_A
UNIX_DAY = 86400
MIN_FEE = PARAMS_DEPLOYER._constants.MIN_FEE
MAX_FEE = PARAMS_DEPLOYER._constants.MAX_FEE
MIN_RAMP_TIME = PARAMS_DEPLOYER._constants.MIN_RAMP_TIME
