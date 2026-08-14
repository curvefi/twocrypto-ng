import boa

from tests.utils.god_mode import GodModePool


def _assert_standalone_view_matches_pool_quote(pool, views_contract):
    gm_pool = GodModePool(pool)
    gm_pool.add_liquidity_balanced(100 * 10**18)

    amount_to_withdraw = gm_pool.balanceOf(boa.env.eoa) // 5

    for coin_idx in range(2):
        standalone_quote = views_contract.calc_withdraw_one_coin(
            amount_to_withdraw,
            coin_idx,
            pool.address,
        )
        pool_quote = pool.calc_withdraw_one_coin(amount_to_withdraw, coin_idx)

        assert standalone_quote == pool_quote

    dx = gm_pool.compute_balanced_amounts(10**18)[0]
    assert views_contract.get_dy(0, 1, dx, pool.address) == pool.get_dy(0, 1, dx)
    dx = gm_pool.compute_balanced_amounts(10**18)[1]
    assert views_contract.get_dy(1, 0, dx, pool.address) == pool.get_dy(1, 0, dx)


def test_standalone_view_calc_withdraw_one_coin_matches_pool_quote(pool, views_contract):
    with boa.env.anchor():
        _assert_standalone_view_matches_pool_quote(pool, views_contract)


def test_standalone_view_calc_withdraw_one_coin_matches_pool_quote_with_policy(
    pool_with_policy_contract,
    views_contract,
):
    with boa.env.anchor():
        _assert_standalone_view_matches_pool_quote(pool_with_policy_contract, views_contract)
