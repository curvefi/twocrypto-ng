"""
Collection of useful strategies for stateful testing,
somewhat redundant due to the fact that we cannot use
fixtures in stateful testing (without compromises).
"""

import boa
from hypothesis.strategies import (
    composite,
    integers,
    just,
    lists,
    sampled_from,
)

# compiling contracts
from contracts.main import CurveCryptoMathOptimized2 as amm_deployer
from contracts.main import CurveCryptoMathOptimized2 as math_deployer
from contracts.main import CurveCryptoViews2Optimized as view_deployer
from contracts.main import CurveTwocryptoFactory as factory_deployer
from contracts.main import LiquidityGauge as gauge_deployer
from tests.utils.constants import (
    MAX_A,
    MAX_FEE,
    MAX_GAMMA,
    MIN_A,
    MIN_FEE,
    MIN_GAMMA,
)

# ---------------- addresses ----------------
# TODO this should use the boa address strategy
# when the recurring address feature gets added
# otherwise its not that useful to have a strategy
deployer = just(boa.env.generate_address())
fee_receiver = just(boa.env.generate_address())
owner = just(boa.env.generate_address())


# ---------------- factory ----------------
@composite
def factory(
    draw,
):
    _deployer = draw(deployer)
    _fee_receiver = draw(fee_receiver)
    _owner = draw(owner)

    with boa.env.prank(_deployer):
        amm_implementation = amm_deployer.deploy_as_blueprint()
        gauge_implementation = gauge_deployer.deploy_as_blueprint()

        view_contract = view_deployer.deploy()
        math_contract = math_deployer.deploy()

        _factory = factory_deployer.deploy()
        _factory.initialise_ownership(_fee_receiver, _owner)

    with boa.env.prank(_owner):
        _factory.set_pool_implementation(amm_implementation, 0)
        _factory.set_gauge_implementation(gauge_implementation)
        _factory.set_views_implementation(view_contract)
        _factory.set_math_implementation(math_contract)

    return _factory


# ---------------- pool deployment params ----------------
A = integers(min_value=MIN_A, max_value=MAX_A)
gamma = integers(min_value=MIN_GAMMA, max_value=MAX_GAMMA)

fee_gamma = integers(min_value=1, max_value=1e18)


@composite
def fees(draw):
    """
    These two needs to be computed together as the value of `out_fee`
    depends on `mid_fee`.
    """
    mid_fee = draw(integers(min_value=MIN_FEE, max_value=MAX_FEE - 2))
    out_fee = draw(integers(min_value=mid_fee, max_value=MAX_FEE - 2))

    return mid_fee, out_fee


allowed_extra_profit = integers(min_value=0, max_value=1e18)
adjustment_step = integers(min_value=1, max_value=1e18)
ma_exp_time = integers(min_value=87, max_value=872541)

# TODO figure out why the upper bound reverts (had to reduce
# because fuzzing seems incorrect)
price = integers(min_value=1e6 + 1, max_value=1e29)

# -------------------- tokens --------------------
# fuzzes a mock ERC20 with variable decimals
token = integers(min_value=0, max_value=18).map(
    lambda x: boa.load("contracts/mocks/ERC20Mock.vy", "USD", "USD", x)
)
weth = just(boa.load("contracts/mocks/WETH.vy"))


# ---------------- pool ----------------
@composite
def pool(draw):
    """
    Creates a factory based pool with the following fuzzed parameters:
    - A
    - gamma
    - mid_fee
    - out_fee
    - tokens: can be a mock erc20 with variable decimals or WETH
    - allowed_extra_profit
    - adjustment_step
    - ma_exp_time
    - initial_price
    """
    _factory = draw(factory())
    mid_fee, out_fee = draw(fees())

    # TODO this should have a lot of tokens with weird behaviors
    tokens = draw(
        lists(
            sampled_from([draw(token), draw(weth)]),
            min_size=2,
            max_size=2,
            unique=True,
        )
    )

    with boa.env.prank(draw(deployer)):
        swap = _factory.deploy_pool(
            "stateful simulation",
            "SIMULATION",
            tokens,
            0,
            draw(A),
            draw(gamma),
            mid_fee,
            out_fee,
            draw(fee_gamma),
            draw(allowed_extra_profit),
            draw(adjustment_step),
            draw(ma_exp_time),
            draw(price),
        )

    return amm_deployer.at(swap)
