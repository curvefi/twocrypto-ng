import boa
import pytest
from boa_zksync.environment import ZERO_ADDRESS


@pytest.fixture(scope="module")
def math_contract(deployer):
    with boa.env.prank(deployer):
        return boa.load("contracts/main/CurveCryptoMathOptimized2.vy")


@pytest.fixture(scope="module")
def gauge_interface():
    return boa.load_partial("contracts/main/LiquidityGauge.vy")


@pytest.fixture(scope="module")
def gauge_implementation(deployer, gauge_interface):
    with boa.env.prank(deployer):
        return boa.env.generate_address()
        return gauge_interface.deploy_as_blueprint()


@pytest.fixture(scope="module")
def amm_interface():
    return boa.load_partial("contracts/main/CurveTwocryptoOptimized.vy")


@pytest.fixture(scope="module")
def amm_implementation(deployer, amm_interface, math_contract):
    with boa.env.prank(deployer):
        return amm_interface.deploy_as_blueprint(
            "Blueprint",  # _name
            "_",  # _symbol
            [ZERO_ADDRESS] * 2,  # _coins
            math_contract,  # _math
            b"\1" * 32,  # _salt
            340282366920938463463374607431768211457,  # packed_precisions
            136112946768375385385349842972852284582400000,  # packed_gamma_A
            8847341539944400050877843276543133320576000000,  # packed_fee_params
            6125082604576892342340742933771827806226,  # packed_rebalancing_params
            1,  # initial_price
        )


@pytest.fixture(scope="module")
def views_contract(deployer):
    with boa.env.prank(deployer):
        return boa.load("contracts/main/CurveCryptoViews2Optimized.vy")


@pytest.fixture(scope="module")
def factory(
    deployer,
    fee_receiver,
    owner,
    amm_implementation,
    gauge_implementation,
    math_contract,
    views_contract,
):
    with boa.env.prank(deployer):
        factory = boa.load("contracts/main/CurveTwocryptoFactory.vy")
        factory.initialise_ownership(fee_receiver, owner)

    with boa.env.prank(owner):
        factory.set_pool_implementation(amm_implementation, 0)
        factory.set_gauge_implementation(gauge_implementation)
        factory.set_views_implementation(views_contract)
        factory.set_math_implementation(math_contract)

    return factory
