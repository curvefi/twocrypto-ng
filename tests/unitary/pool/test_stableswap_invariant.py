import pytest
import boa

from tests.unitary.utils import GodModePool

factory_deployer = boa.load_partial("contracts/main/TwocryptoFactory.vy")
s_amm_deployer = boa.load_partial("contracts/stableswap_invariant/TwocryptoStableswap.vy")
s_math_deployer = boa.load_partial("contracts/stableswap_invariant/TwocryptoStableswapMath.vy")


@pytest.fixture
def factory():
    _deployer = boa.env.generate_address()
    _fee_receiver = boa.env.generate_address()
    _owner = boa.env.generate_address()

    # assume(_fee_receiver != _owner != _deployer)

    with boa.env.prank(_deployer):
        amm_implementation = s_amm_deployer.deploy_as_blueprint()
        # gauge_implementation = gauge_deployer.deploy_as_blueprint()

        # view_contract = view_deployer.deploy()
        math_contract = s_math_deployer.deploy()
        print(math_contract.address)

        _factory = factory_deployer.deploy()
        _factory.initialise_ownership(_fee_receiver, _owner)

    with boa.env.prank(_owner):
        _factory.set_pool_implementation(amm_implementation, 0)
        # _factory.set_gauge_implementation(gauge_implementation)
        # _factory.set_views_implementation(view_contract)
        _factory.set_math_implementation(math_contract)

    return _factory


@pytest.fixture()
def tokens():
    tgen = boa.load_partial(
        "contracts/mocks/ERC20Mock.vy",
    )
    return [tgen("test", "test", 18), tgen("test", "test", 18)]


@pytest.fixture
def stable_pool(
    factory,
    params,
    tokens,
):
    print(params)
    print(tokens)
    """Creates a factory based pool with the following fuzzed parameters:
    Custom strategies can be passed as argument to override the default
    """

    pool = factory.deploy_pool(
        "stateful simulation",
        "SIMULATION",
        tokens,
        0,
        params["A"],
        params["gamma"],
        params["mid_fee"],
        params["out_fee"],
        params["fee_gamma"],
        params["allowed_extra_profit"],
        params["adjustment_step"],
        params["ma_time"],
        params["initial_prices"][
            1
        ],  # TODO careful started on diff prices even tho stableswap invariant is used
    )

    pool = s_amm_deployer.at(pool)

    return GodModePool(pool, tokens)


def test_simple(stable_pool):
    amounts = [10**18, 10**18]

    stable_pool.add_liquidity(amounts)
