import copy

import boa


def _apply_new_params(pool, params):
    pool.apply_new_parameters(
        params["mid_fee"],
        params["out_fee"],
        params["fee_gamma"],
        params["allowed_extra_profit"],
        params["adjustment_step"],
        params["ma_time"],
    )


def test_commit_accept_mid_fee(pool, factory_admin, params):
    p = copy.deepcopy(params)
    p["mid_fee"] = p["mid_fee"] + 1
    with boa.env.prank(factory_admin):
        _apply_new_params(pool, p)

    mid_fee = pool.internal._unpack_3(pool._storage.packed_fee_params.get())[0]
    assert mid_fee == p["mid_fee"]


def test_commit_accept_out_fee(pool, factory_admin, params):
    p = copy.deepcopy(params)
    p["out_fee"] = p["out_fee"] + 1
    with boa.env.prank(factory_admin):
        _apply_new_params(pool, p)

    out_fee = pool.internal._unpack_3(pool._storage.packed_fee_params.get())[1]
    assert out_fee == p["out_fee"]


def test_commit_accept_fee_gamma(pool, factory_admin, params):
    p = copy.deepcopy(params)
    p["fee_gamma"] = 10**17
    with boa.env.prank(factory_admin):
        _apply_new_params(pool, p)

    fee_gamma = pool.internal._unpack_3(pool._storage.packed_fee_params.get())[2]
    assert fee_gamma == p["fee_gamma"]


def test_commit_accept_fee_params(pool, factory_admin, params):
    p = copy.deepcopy(params)
    p["mid_fee"] += 1
    p["out_fee"] += 1
    p["fee_gamma"] = 10**17

    with boa.env.prank(pool.admin()):
        _apply_new_params(pool, p)

    fee_params = pool.internal._unpack_3(pool._storage.packed_fee_params.get())
    assert fee_params[0] == p["mid_fee"]
    assert fee_params[1] == p["out_fee"]
    assert fee_params[2] == p["fee_gamma"]


def test_commit_accept_allowed_extra_profit(pool, factory_admin, params):
    p = copy.deepcopy(params)
    p["allowed_extra_profit"] = 10**17
    with boa.env.prank(factory_admin):
        _apply_new_params(pool, p)

    allowed_extra_profit = pool.internal._unpack_3(pool._storage.packed_rebalancing_params.get())[0]
    assert allowed_extra_profit == p["allowed_extra_profit"]


def test_commit_accept_adjustment_step(pool, factory_admin, params):
    p = copy.deepcopy(params)
    p["adjustment_step"] = 10**17
    with boa.env.prank(factory_admin):
        _apply_new_params(pool, p)

    adjustment_step = pool.internal._unpack_3(pool._storage.packed_rebalancing_params.get())[1]
    assert adjustment_step == p["adjustment_step"]


def test_commit_accept_ma_time(pool, factory_admin, params):
    p = copy.deepcopy(params)
    p["ma_time"] = 872
    with boa.env.prank(factory_admin):
        _apply_new_params(pool, p)

    ma_time = pool.internal._unpack_3(pool._storage.packed_rebalancing_params.get())[2]
    assert ma_time == p["ma_time"]


def test_commit_accept_rebalancing_params(pool, factory_admin, params):
    p = copy.deepcopy(params)
    p["allowed_extra_profit"] = 10**17
    p["adjustment_step"] = 10**17
    p["ma_time"] = 1000

    with boa.env.prank(factory_admin):
        _apply_new_params(pool, p)

    rebalancing_params = pool.internal._unpack_3(pool._storage.packed_rebalancing_params.get())
    assert rebalancing_params[0] == p["allowed_extra_profit"]
    assert rebalancing_params[1] == p["adjustment_step"]
    assert rebalancing_params[2] == p["ma_time"]
