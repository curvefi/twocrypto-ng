import boa

from tests.conftest import (
    INITIAL_PRICES,
    _crypto_swap_with_deposit,
    _deploy_pool,
    _get_deposit_amounts,
)
from tests.utils.constants import POOL_DEPLOYER


def _fresh_standard_pool(factory, coins, params, deployer):
    return POOL_DEPLOYER.at(_deploy_pool(factory, params, coins, deployer))


def _fresh_embedded_pool(factory_with_embedded_periphery, coins, params, deployer):
    return POOL_DEPLOYER.at(_deploy_pool(factory_with_embedded_periphery, params, coins, deployer))


def test_embedded_periphery_pool_has_view_and_math_on_deploy(
    embedded_pool,
    views_contract,
    math_contract,
):
    assert embedded_pool.VIEW() == views_contract.address
    assert embedded_pool.MATH() == math_contract.address


def test_embedded_periphery_first_deposit_and_quotes_work(
    embedded_pool,
    coins,
    user,
    views_contract,
):
    with boa.env.anchor():
        _crypto_swap_with_deposit(coins, user, embedded_pool, INITIAL_PRICES)

        dx0, dx1 = _get_deposit_amounts(10**5, INITIAL_PRICES, coins)
        assert embedded_pool.get_dy(0, 1, dx0) == views_contract.get_dy(
            0, 1, dx0, embedded_pool.address
        )
        assert embedded_pool.get_dy(1, 0, dx1) == views_contract.get_dy(
            1, 0, dx1, embedded_pool.address
        )

        next_amounts = _get_deposit_amounts(2 * 10**5, INITIAL_PRICES, coins)
        assert embedded_pool.calc_token_amount(next_amounts, True) > 0


def test_embedded_periphery_matches_standard_pool_quotes(
    factory,
    factory_with_embedded_periphery,
    coins,
    params,
    deployer,
    user,
):
    with boa.env.anchor():
        standard_pool = _fresh_standard_pool(factory, coins, params, deployer)
        embedded_pool = _fresh_embedded_pool(
            factory_with_embedded_periphery, coins, params, deployer
        )

        _crypto_swap_with_deposit(coins, user, standard_pool, INITIAL_PRICES)
        _crypto_swap_with_deposit(coins, user, embedded_pool, INITIAL_PRICES)

        dx0, dx1 = _get_deposit_amounts(10**5, INITIAL_PRICES, coins)
        assert embedded_pool.get_dy(0, 1, dx0) == standard_pool.get_dy(0, 1, dx0)
        assert embedded_pool.get_dy(1, 0, dx1) == standard_pool.get_dy(1, 0, dx1)

        next_amounts = _get_deposit_amounts(2 * 10**5, INITIAL_PRICES, coins)
        assert embedded_pool.calc_token_amount(
            next_amounts, True
        ) == standard_pool.calc_token_amount(
            next_amounts,
            True,
        )
