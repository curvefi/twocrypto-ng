import boa
import pytest

from hypothesis import assume

# compiling contracts
from contracts.main import CurveCryptoViews2Optimized as view_deployer
from contracts.main import CurveTwocryptoFactory as factory_deployer

from contracts.main import CurveTwocryptoOptimized as amm_deployer
from contracts.main import CurveCryptoMathOptimized2 as math_deployer
from contracts.experimental.initial_guess import CurveTwocryptoOptimized as amm_deployer_initial_guess
from contracts.experimental.initial_guess import CurveCryptoMathOptimized2 as math_deployer_initial_guess
from tests.utils.tokens import mint_for_testing

# ---------------- addresses ----------------
address = boa.test.strategy("address")
deployer = address
fee_receiver = address
owner = address
params = {
    "A": 400000,
    "gamma": 145000000000000,
    "mid_fee": 26000000,
    "out_fee": 45000000,
    "allowed_extra_profit": 2000000000000,
    "fee_gamma": 230000000000000,
    "adjustment_step": 146000000000000,
    "ma_exp_time": 866,  # # 600 seconds//math.log(2)
    "price": 4000 * 10**18,
}


def _deposit_initial_liquidity(pool, tokens):
    
    # deposit:
    user = boa.env.generate_address()
    quantities = [10**6 * 10**36 // p for p in [10**18, params["price"]]]  # $2M worth

    for coin, quantity in zip(tokens, quantities):
        # mint coins for user:
        mint_for_testing(coin, user, quantity)
        assert coin.balanceOf(user) == quantity

        # approve crypto_swap to trade coin for user:
        with boa.env.prank(user):
            coin.approve(pool, 2**256 - 1)

    # Very first deposit
    with boa.env.prank(user):
        pool.add_liquidity(quantities, 0)
        
    return pool


@pytest.fixture(scope="module")
def tokens():
    return [
    boa.load("contracts/mocks/ERC20Mock.vy", "tkn_a", "tkn_a", 18), 
    boa.load("contracts/mocks/ERC20Mock.vy", "tkn_b", "tkn_b", 18)
]


@pytest.fixture(scope="module")
def factory_no_initial_guess():
    
    _deployer = boa.env.generate_address()
    _fee_receiver = boa.env.generate_address()
    _owner = boa.env.generate_address()

    with boa.env.prank(_deployer):

        amm_implementation = amm_deployer.deploy_as_blueprint()
        math_contract = math_deployer.deploy()
        view_contract = view_deployer.deploy()

        _factory = factory_deployer.deploy()
        _factory.initialise_ownership(_fee_receiver, _owner)

    with boa.env.prank(_owner):
        _factory.set_views_implementation(view_contract)
        _factory.set_math_implementation(math_contract)
        
        # set pool implementations:
        _factory.set_pool_implementation(amm_implementation, 0)
        
    return _factory


@pytest.fixture(scope="module")
def factory_initial_guess():
    
    _deployer = boa.env.generate_address()
    _fee_receiver = boa.env.generate_address()
    _owner = boa.env.generate_address()

    assume(_fee_receiver != _owner != _deployer)

    with boa.env.prank(_deployer):
        amm_implementation = amm_deployer_initial_guess.deploy_as_blueprint()
        math_contract = math_deployer_initial_guess.deploy()
        view_contract = view_deployer.deploy()

        _factory = factory_deployer.deploy()
        _factory.initialise_ownership(_fee_receiver, _owner)

    with boa.env.prank(_owner):
        _factory.set_views_implementation(view_contract)
        _factory.set_math_implementation(math_contract)
        
        # set pool implementations:
        _factory.set_pool_implementation(amm_implementation, 0)
        
    return _factory


@pytest.fixture(scope="module")
def pool(factory, tokens):

    with boa.env.prank(boa.env.generate_address()):
        _pool = factory.deploy_pool(
            "test_A",
            "test_A",
            tokens,
            0,
            params["A"],
            params["gamma"],
            params["mid_fee"],
            params["out_fee"],
            params["fee_gamma"],
            params["allowed_extra_profit"],
            params["adjustment_step"],
            params["ma_exp_time"],
            params["price"],
        )

    _pool = amm_deployer.at(_pool)
    return _deposit_initial_liquidity(_pool, tokens)


@pytest.fixture(scope="module")
def pool_initial_guess(factory_initial_guess, tokens):

    with boa.env.prank(boa.env.generate_address()):
        _pool = factory_initial_guess.deploy_pool(
            "test_B",
            "test_B",
            tokens,
            0,
            params["A"],
            params["gamma"],
            params["mid_fee"],
            params["out_fee"],
            params["fee_gamma"],
            params["allowed_extra_profit"],
            params["adjustment_step"],
            params["ma_exp_time"],
            params["price"],
        )

    _pool = amm_deployer.at(_pool)
    return _deposit_initial_liquidity(_pool, tokens)


@pytest.fixture(scope="module")
def pools(pool, pool_initial_guess):
    return [pool, pool_initial_guess]
