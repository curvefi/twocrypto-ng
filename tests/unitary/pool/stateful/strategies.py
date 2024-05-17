"""
Collection of useful strategies for stateful testing,
somewhat redundant due to the fact that we cannot use
fixtures in stateful testing (without compromises).
"""

import boa
from boa.test import strategy
from hypothesis import Phase, assume, note, settings
from hypothesis.strategies import (
    composite,
    integers,
    just,
    lists,
    sampled_from,
)

# compiling contracts
from contracts.main import CurveCryptoMathOptimized2 as math_deployer
from contracts.main import CurveCryptoViews2Optimized as view_deployer
from contracts.main import CurveTwocryptoFactory as factory_deployer
from contracts.main import CurveTwocryptoOptimized as amm_deployer
from contracts.main import LiquidityGauge as gauge_deployer
from tests.utils.constants import (
    MAX_A,
    MAX_FEE,
    MAX_GAMMA,
    MIN_A,
    MIN_FEE,
    MIN_GAMMA,
)

# ---------------- hypothesis test profiles ----------------
settings.register_profile("no-shrink", settings(phases=list(Phase)[:4]))

# just a more hyptohesis-like way to get an address
# from boa's search strategy
address = strategy("address")

# ---------------- addresses ----------------
deployer = address
fee_receiver = address
owner = address


# ---------------- factory ----------------
@composite
def factory(
    draw,
):
    _deployer = draw(deployer)
    _fee_receiver = draw(fee_receiver)
    _owner = draw(owner)

    assume(_fee_receiver != _owner != _deployer)

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

MIN_PRICE = 1e6 + 1
MAX_PRICE = 1e29

price = integers(min_value=MIN_PRICE, max_value=MAX_PRICE)

# -------------------- tokens --------------------
# TODO restore variable decimals
# token = integers(min_value=0, max_value=18).map(
token = just(18).map(  # TODO restore variable decimals
    lambda x: boa.load("contracts/mocks/ERC20Mock.vy", "USD", "USD", x)
)
# TODO add more tokens
weth = just(boa.load("contracts/mocks/WETH.vy"))


# ---------------- pool ----------------
@composite
def pool(
    draw,
    A=A,
    gamma=gamma,
    fees=fees,
    fee_gamma=fee_gamma,
    allowed_extra_profit=allowed_extra_profit,
    adjustment_step=adjustment_step,
    ma_exp_time=ma_exp_time,
    price=price,
):
    """Creates a factory based pool with the following fuzzed parameters:
    Custom strategies can be passed as argument to override the default
    """

    # Creates a factory based pool with the following fuzzed parameters:
    _factory = draw(factory())
    mid_fee, out_fee = draw(fees())

    # TODO this should have a lot of tokens with weird behaviors and weth
    tokens = draw(
        lists(
            sampled_from([draw(token), draw(token)]),
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

    swap = amm_deployer.at(swap)

    note(
        "deployed pool with "
        + "A: {:.2e}".format(swap.A())
        + ", gamma: {:.2e}".format(swap.gamma())
        + ", price: {:.2e}".format(swap.price_oracle())
        + ", fee_gamma: {:.2e}".format(swap.fee_gamma())
        + ", allowed_extra_profit: {:.2e}".format(swap.allowed_extra_profit())
        + ", adjustment_step: {:.2e}".format(swap.adjustment_step())
    )
    return swap
