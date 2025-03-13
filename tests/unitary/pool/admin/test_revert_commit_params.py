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


def test_commit_incorrect_fee_params(pool, factory_admin, params):
    p = copy.deepcopy(params)
    p["mid_fee"] = p["out_fee"] + 1
    with boa.env.prank(factory_admin):
        with boa.reverts("mid-fee is too high"):
            _apply_new_params(pool, p)

        p["out_fee"] = 0
        with boa.reverts("fee is out of range"):
            _apply_new_params(pool, p)

        # too large out_fee revert to old out_fee:
        p["mid_fee"] = params["mid_fee"]
        p["out_fee"] = 10**10 + 1  # <-- MAX_FEE
        _apply_new_params(pool, p)
        log = pool.get_logs()[0]
        assert log.out_fee == params["out_fee"]


def test_commit_incorrect_fee_gamma(pool, factory_admin, params):
    p = copy.deepcopy(params)
    p["fee_gamma"] = 0

    with boa.env.prank(factory_admin):
        with boa.reverts("fee_gamma out of range [1 .. 10**18]"):
            _apply_new_params(pool, p)

        p["fee_gamma"] = 10**18 + 1
        _apply_new_params(pool, p)

    # it will not change fee_gamma as it is above 10**18
    assert pool.get_logs()[0].fee_gamma == params["fee_gamma"]


def test_commit_rebalancing_params(pool, factory_admin, params):
    p = copy.deepcopy(params)
    p["allowed_extra_profit"] = 10**18 + 1
    p["adjustment_step"] == 10**18 + 1
    p["ma_time"] = 872542 + 1

    with boa.env.prank(factory_admin):
        with boa.env.anchor():
            _apply_new_params(pool, p)
            logs = pool.get_logs()[0]

            # values revert to contract's storage values:
            assert logs.allowed_extra_profit == params["allowed_extra_profit"]
            assert logs.adjustment_step == params["adjustment_step"]
            assert logs.ma_time == params["ma_time"]

        with boa.reverts("MA time should be longer than 60/ln(2)"):
            p["ma_time"] = 86
            _apply_new_params(pool, p)


def test_revert_unauthorised_commit(pool, user, params):
    with boa.env.prank(user), boa.reverts("only owner"):
        _apply_new_params(pool, params)
