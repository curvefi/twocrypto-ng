import boa
import pytest

INITIAL_PRICES = [10**18, 1500 * 10**18]  # price relative to coin_id = 0


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


@pytest.fixture(scope="module")
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


@pytest.fixture(scope="module")
def swap(
    factory,
    amm_interface,
    coins,
    params,
    deployer,
):
    with boa.env.prank(deployer):
        swap = factory.deploy_pool(
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

    return amm_interface.at(swap)


@pytest.fixture(scope="module")
def swap_with_deposit(swap, coins, user):
    return _crypto_swap_with_deposit(coins, user, swap, INITIAL_PRICES)


@pytest.fixture(scope="module")
def yuge_swap(swap, coins, user):
    return _crypto_swap_with_deposit(coins, user, swap, INITIAL_PRICES, dollar_amt_each_coin=10**10)
