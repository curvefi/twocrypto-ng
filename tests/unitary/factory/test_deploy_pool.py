import boa
import pytest

from tests.utils.constants import FACTORY_DEPLOYER
from tests.utils.constants import packing_utils

# TODO move this to constants
ZERO_ADDRESS = boa.eval("empty(address)")


@pytest.fixture(scope="module")
def empty_factory(deployer, fee_receiver, owner):
    with boa.env.prank(deployer):
        factory = FACTORY_DEPLOYER.deploy()

    assert factory.admin() == ZERO_ADDRESS
    assert factory.fee_receiver() == ZERO_ADDRESS

    with boa.env.prank(deployer):
        factory.initialise_ownership(fee_receiver, owner)

    assert factory.admin() == owner
    assert factory.fee_receiver() == fee_receiver

    return factory


def test_deployer_cannot_set_ownership_twice(empty_factory, deployer):
    with boa.env.prank(deployer), boa.reverts():
        empty_factory.initialise_ownership(boa.env.generate_address(), boa.env.generate_address())


def test_nondeployer_cannot_set_ownership(deployer):
    with boa.env.prank(deployer):
        factory = FACTORY_DEPLOYER.deploy()

    with boa.env.prank(boa.env.generate_address()), boa.reverts():
        factory.initialise_ownership(boa.env.generate_address(), boa.env.generate_address())
    assert factory.admin() == ZERO_ADDRESS
    assert factory.fee_receiver() == ZERO_ADDRESS


def test_check_packed_params_on_deployment(pool, params, coins):
    # check packed precisions
    unpacked_precisions = pool.precisions()
    for i in range(len(coins)):
        assert unpacked_precisions[i] == 10 ** (18 - coins[i].decimals())

    # check packed fees
    unpacked_fees = packing_utils.internal.unpack_3(pool._storage.packed_fee_params.get())
    assert params["mid_fee"] == unpacked_fees[0]
    assert params["out_fee"] == unpacked_fees[1]
    assert params["fee_gamma"] == unpacked_fees[2]

    # check packed rebalancing params
    unpacked_rebalancing_params = packing_utils.internal.unpack_3(
        pool._storage.packed_rebalancing_params.get()
    )
    assert params["allowed_extra_profit"] == unpacked_rebalancing_params[0]
    assert params["adjustment_step"] == unpacked_rebalancing_params[1]
    assert params["ma_time"] == unpacked_rebalancing_params[2]

    # check packed A_gamma
    A = pool.A()
    gamma = pool.gamma()
    assert params["A"] == A
    assert params["gamma"] == gamma

    # check packed_prices
    assert pool.price_oracle() == params["initial_prices"][1]
    assert pool.price_scale() == params["initial_prices"][1]
    assert pool.last_prices() == params["initial_prices"][1]


def test_check_pool_data_on_deployment(pool, factory, coins):
    for i, coin_a in enumerate(coins):
        for j, coin_b in enumerate(coins):
            if coin_a == coin_b:
                continue

            assert factory.find_pool_for_coins(coin_a, coin_b).lower() == pool.address.lower()

            factory.get_coin_indices(pool.address, coin_a, coin_b) == (i, j)

    pool_coins = factory.get_coins(pool.address)
    coins_lower = [coin.address.lower() for coin in coins]
    for i in range(len(pool_coins)):
        assert pool_coins[i].lower() == coins_lower[i]

    pool_decimals = list(factory.get_decimals(pool.address))
    assert pool_decimals == [coin.decimals() for coin in coins]


def test_revert_deploy_without_implementations(
    empty_factory,
    coins,
    params,
    deployer,
):
    with boa.env.prank(deployer):
        with boa.reverts("pool implementation not set"):
            empty_factory.deploy_pool(
                "Test",  # _name: String[64]
                "Test",  # _symbol: String[32]
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
