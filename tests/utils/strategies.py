"""
Collection of useful strategies for stateful testing,
somewhat redundant due to the fact that we cannot use
fixtures in stateful testing (without compromises).
"""

import boa
from boa.test import strategy
from hypothesis import assume, note
from hypothesis.strategies import composite, integers, just, sampled_from

from tests.utils.constants import (
    ERC20_DEPLOYER,
    FACTORY_DEPLOYER,
    GAUGE_DEPLOYER,
    MATH_DEPLOYER,
    MAX_A,
    MAX_FEE,
    MAX_GAMMA,
    MIN_A,
    MIN_FEE,
    MIN_GAMMA,
    POOL_DEPLOYER,
    VIEW_DEPLOYER,
)
from tests.utils.embedded_periphery import load_twocrypto_with_embedded_periphery
from tests.utils.pool_presets import all_presets

# ---------------- hypothesis test profiles ----------------

# just a more hypothesis-like way to get an address
# from boa's search strategy
address = strategy("address")

# ---------------- addresses ----------------
deployer = address
fee_receiver = address
owner = address


def _deploy_shared_implementations():
    # These are intentionally deployed at module import time so they live
    # outside pytest/boa per-test and per-example anchors. Stateful tests run
    # Hypothesis examples under nested `boa.env.anchor()` contexts, so a lazy
    # cache populated inside an example would be reverted away after that
    # example completes.
    shared_deployer = boa.env.generate_address()
    boa.env.set_balance(shared_deployer, 10**25)

    with boa.env.prank(shared_deployer):
        view_contract = VIEW_DEPLOYER.deploy()
        math_contract = MATH_DEPLOYER.deploy()
        pool_implementation = load_twocrypto_with_embedded_periphery(
            view_contract.address,
            math_contract.address,
        ).deploy_as_blueprint()
        gauge_implementation = GAUGE_DEPLOYER.deploy_as_blueprint()

    return (
        view_contract,
        math_contract,
        pool_implementation,
        gauge_implementation,
    )


_SHARED_IMPLEMENTATIONS = _deploy_shared_implementations()


def _deploy_shared_tokens():
    # Similar to the implementation cache, deploy token mocks once per worker
    # outside Hypothesis example anchors so stateful examples can reuse them.
    shared_deployer = boa.env.generate_address()
    boa.env.set_balance(shared_deployer, 10**25)

    token_bank = {}
    with boa.env.prank(shared_deployer):
        for decimals in [18, 9, 8, 6]:
            token_bank[decimals] = [
                ERC20_DEPLOYER.deploy(f"USD-{decimals}-{i}", f"USD{i}", decimals) for i in range(3)
            ]

    return token_bank


_SHARED_TOKENS = _deploy_shared_tokens()


# ---------------- factory ----------------
@composite
def factory(
    draw,
):
    _deployer = draw(deployer)
    _fee_receiver = draw(fee_receiver)
    _owner = draw(owner)

    assume(_fee_receiver != _owner != _deployer)

    view_contract, math_contract, pool_implementation, gauge_implementation = (
        _SHARED_IMPLEMENTATIONS
    )

    with boa.env.prank(_deployer):
        _factory = FACTORY_DEPLOYER.deploy()
        _factory.initialise_ownership(_fee_receiver, _owner)

    with boa.env.prank(_owner):
        _factory.set_pool_implementation(pool_implementation, 0)
        _factory.set_gauge_implementation(gauge_implementation)
        _factory.set_views_implementation(view_contract)
        _factory.set_math_implementation(math_contract)

    return _factory


# ---------------- pool deployment params ----------------
A = integers(min_value=MIN_A, max_value=MAX_A)
gamma = integers(min_value=MIN_GAMMA, max_value=MAX_GAMMA)

fee_gamma = integers(min_value=1, max_value=10**18)


@composite
def fees(draw):
    """
    These two needs to be computed together as the value of `out_fee`
    depends on `mid_fee`.
    """
    mid_fee = draw(integers(min_value=MIN_FEE, max_value=MAX_FEE - 2))
    out_fee = draw(integers(min_value=mid_fee, max_value=MAX_FEE - 2))

    return mid_fee, out_fee


adjustment_step_min = integers(min_value=1, max_value=10**18 - 1)
adjustment_step_max = integers(min_value=1, max_value=10**18)
ma_exp_time = integers(min_value=87, max_value=872541)

# 1e26 is less than the maximum amount allowed by the factory
# however testing with a smaller number is more realistic
# and less cumbersome
price = integers(min_value=int(1e10), max_value=int(1e26))

# -------------------- tokens --------------------


@composite
def token_pair(draw):
    decimals_0 = draw(sampled_from([18, 9, 8, 6]))
    decimals_1 = draw(sampled_from([18, 9, 8, 6]))
    tokens_0 = _SHARED_TOKENS[decimals_0]
    tokens_1 = _SHARED_TOKENS[decimals_1]

    token_0 = draw(sampled_from(tokens_0))
    if decimals_0 == decimals_1:
        token_1 = draw(sampled_from([t for t in tokens_1 if t.address != token_0.address]))
    else:
        token_1 = draw(sampled_from(tokens_1))

    return [token_0, token_1]


# ---------------- pool ----------------
@composite
def pool(
    draw,
    A=A,
    gamma=gamma,
    fees=fees(),
    fee_gamma=fee_gamma,
    adjustment_step_min=adjustment_step_min,
    adjustment_step_max=adjustment_step_max,
    ma_exp_time=ma_exp_time,
    price=price,
):
    """Creates a factory based pool with the following fuzzed parameters:
    Custom strategies can be passed as argument to override the default
    """
    boa.env.evm.patch.timestamp = 1_000_000
    # Creates a factory based pool with the following fuzzed parameters:
    _factory = draw(factory())
    mid_fee, out_fee = draw(fees)

    # TODO should test weird tokens as well (non-standard/non-compliant)
    tokens = draw(token_pair())

    with boa.env.prank(draw(deployer)):
        adj_min = draw(adjustment_step_min)
        adj_max = draw(adjustment_step_max)
        assume(adj_max > adj_min)
        _pool = _factory.deploy_pool(
            "stateful simulation",
            "SIMULATION",
            tokens,
            0,
            draw(A),
            draw(gamma),
            mid_fee,
            out_fee,
            draw(fee_gamma),
            adj_min,
            adj_max,
            draw(ma_exp_time),
            draw(price),
        )

    _pool = POOL_DEPLOYER.at(_pool)

    note(
        "deployed pool with "
        + "A: {:.2e}".format(_pool.A())
        + ", gamma: {:.2e}".format(_pool.gamma())
        + ", price: {:.2e}".format(_pool.price_oracle())
        + ", fee_gamma: {:.2e}".format(_pool.fee_gamma())
        + ", adjustment_step_min: {:.2e}".format(_pool.adjustment_step()[0])
        + ", adjustment_step_max: {:.2e}".format(_pool.adjustment_step()[1])
        + "\n    coin 0 has {} decimals".format(tokens[0].decimals())
        + "\n    coin 1 has {} decimals".format(tokens[1].decimals())
    )
    return _pool


@composite
def pool_from_preset(draw, preset=sampled_from(all_presets)):
    params = draw(preset)

    note("[POOL PRESET: {}] \n {}".format(params["name"], params["description"]))

    return draw(
        pool(
            A=just(params["A"]),
            gamma=just(params["gamma"]),
            fees=just((params["mid_fee"], params["out_fee"])),
            fee_gamma=just(params["fee_gamma"]),
            adjustment_step_min=just(params["adjustment_step_min"]),
            adjustment_step_max=just(params["adjustment_step_max"]),
            ma_exp_time=just(params["ma_exp_time"]),
        )
    )
