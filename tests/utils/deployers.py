import boa

MATH_DEPLOYER = boa.load_partial("contracts/main/TwocryptoMath.vy")
VIEW_DEPLOYER = boa.load_partial("contracts/main/TwocryptoView.vy")
FACTORY_DEPLOYER = boa.load_partial("contracts/main/TwocryptoFactory.vy")
POOL_DEPLOYER = boa.load_partial("contracts/Twocrypto/Twocrypto.vy")
GAUGE_DEPLOYER = boa.load_partial("contracts/main/LiquidityGauge.vy")
ERC20_DEPLOYER = boa.load_partial("tests/mocks/ERC20Mock.vy")

# TODO this should be tested from twocrypto directly
# temporary workaround till https://github.com/vyperlang/titanoboa/issues/393 is fixed
packing_utils = boa.load("contracts/helpers/packing_utils.vy")
