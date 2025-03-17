from pytest import fixture
from tests.utils.god_mode import GodModePool
from tests.utils.constants import (
    MATH_DEPLOYER,
    GAUGE_DEPLOYER,
    POOL_DEPLOYER,
    VIEW_DEPLOYER,
    FACTORY_DEPLOYER,
    ERC20_DEPLOYER,
)
import boa

# Constants
INITIAL_PRICES = [10**18, 1500 * 10**18]  # price relative to coin_id = 0


# Helper functions
def _get_deposit_amounts(amount_per_token_usd, initial_prices, coins):
    precisions = [10 ** coin.decimals() for coin in coins]

    deposit_amounts = [
        amount_per_token_usd * precision * 10**18 // price
        for price, precision in zip(initial_prices, precisions)
    ]
    return deposit_amounts


def _crypto_swap_with_deposit(
    coins,
    user,
    twocrypto_swap,
    initial_prices,
    dollar_amt_each_coin=int(1.5 * 10**6),
):
    # add 1M of each token to the pool
    quantities = _get_deposit_amounts(dollar_amt_each_coin, initial_prices, coins)

    for coin, quantity in zip(coins, quantities):
        # mint coins for user:
        user_balance = coin.balanceOf(user)
        boa.deal(coin, user, quantity)
        assert coin.balanceOf(user) == user_balance + quantity

        # approve crypto_swap to trade coin for user:
        with boa.env.prank(user):
            coin.approve(twocrypto_swap, 2**256 - 1)

    # Very first deposit
    with boa.env.prank(user):
        twocrypto_swap.add_liquidity(quantities, 0)

    return twocrypto_swap


# Account fixtures
@fixture(scope="module")
def deployer():
    return boa.env.generate_address()


@fixture(scope="module")
def owner():
    return boa.env.generate_address()


@fixture(scope="module")
def factory_admin(factory):
    return factory.admin()


@fixture(scope="module")
def fee_receiver():
    return boa.env.generate_address()


@fixture(scope="module")
def user():
    acc = boa.env.generate_address()
    boa.env.set_balance(acc, 10**25)
    return acc


@fixture(scope="module")
def users():
    accs = [i() for i in [boa.env.generate_address] * 10]
    for acc in accs:
        boa.env.set_balance(acc, 10**25)
    return accs


@fixture(scope="module")
def alice():
    acc = boa.env.generate_address()
    boa.env.set_balance(acc, 10**25)
    return acc


@fixture(scope="module")
def loaded_alice(pool, alice):
    boa.deal(pool, alice, 10**21)
    return alice


@fixture(scope="module")
def bob():
    acc = boa.env.generate_address()
    boa.env.set_balance(acc, 10**25)
    return acc


@fixture(scope="module")
def charlie():
    acc = boa.env.generate_address()
    boa.env.set_balance(acc, 10**25)
    return acc


@fixture(scope="module")
def coins():
    return [ERC20_DEPLOYER.deploy("USD", "USD", 18), ERC20_DEPLOYER.deploy("BTC", "BTC", 18)]


# Factory fixtures
@fixture(scope="module")
def math_contract(deployer):
    with boa.env.prank(deployer):
        return MATH_DEPLOYER.deploy()


@fixture(scope="module")
def gauge_implementation(deployer):
    with boa.env.prank(deployer):
        return GAUGE_DEPLOYER.deploy_as_blueprint()


@fixture(scope="module")
def amm_implementation(deployer):
    with boa.env.prank(deployer):
        return POOL_DEPLOYER.deploy_as_blueprint()


@fixture(scope="module")
def views_contract(deployer):
    with boa.env.prank(deployer):
        return VIEW_DEPLOYER.deploy()


@fixture(scope="module")
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
        factory = FACTORY_DEPLOYER.deploy()
        factory.initialise_ownership(fee_receiver, owner)

    with boa.env.prank(owner):
        factory.set_pool_implementation(amm_implementation, 0)
        factory.set_gauge_implementation(gauge_implementation)
        factory.set_views_implementation(views_contract)
        factory.set_math_implementation(math_contract)

    return factory


# Pool fixtures
@fixture(scope="module")
def params():
    return {
        "A": 400000,
        "gamma": 145000000000000,
        "mid_fee": 26000000,
        "out_fee": 45000000,
        "allowed_extra_profit": 2000000000000,
        "fee_gamma": 230000000000000,
        "adjustment_step": 146000000000000,
        "ma_time": 866,  # # 600 seconds//math.log(2)
        "initial_prices": INITIAL_PRICES,
    }


@fixture(scope="module")
def pool(
    factory,
    coins,
    params,
    deployer,
):
    with boa.env.prank(deployer):
        pool = factory.deploy_pool(
            "Curve.fi USD<>WETH",  # _name: String[64]
            "USD<>WETH",  # _symbol: String[32]
            [coin.address for coin in coins],  # _coins: address[N_COINS]
            0,  # implementation_id: uint256
            params["A"],  # A: uint256
            params["gamma"],  # gamma: uint256
            params["mid_fee"],  # mid_fee: uint256
            params["out_fee"],  # out_fee: uint256
            params["fee_gamma"],  # fee_gamma: uint256
            params["allowed_extra_profit"],  # allowed_extra_profit: uint256
            params["adjustment_step"],  # adjustment_step: uint256
            params["ma_time"],  # ma_exp_time: uint256
            params["initial_prices"][1],  # initial_price: uint256
        )

    return POOL_DEPLOYER.at(pool)


@fixture(scope="module")
def gm_pool(pool, coins):
    return GodModePool(pool, coins)


@fixture(scope="module")
def pool_with_deposit(pool, coins, user):
    return _crypto_swap_with_deposit(coins, user, pool, INITIAL_PRICES)
