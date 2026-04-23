import boa

from tests.conftest import _deploy_pool
from tests.utils.constants import FEE_PRECISION, POOL_DEPLOYER
from tests.utils.god_mode import GodModePool


WAD = 10**18
FORCE_TWEAK_MAX_SPOT_DEVIATION_WAD = 10**10
TARGET_GAP_WAD = 6 * 10**12
ONE_BPS_FEE = FEE_PRECISION // 10_000


def _spot(pool):
    return pool.calc_force_tweak_price([0, 0], pool.price_scale())[1]


def _rel_diff_wad(a, b):
    return abs(a - b) * WAD // b


def _signed_rel_diff_wad(a, b):
    if a >= b:
        return (a - b) * WAD // b
    return -((b - a) * WAD // b)


def _trade_spot_up_to(pool, target_spot):
    gm_pool = GodModePool(pool)

    def spot_after(dx):
        with boa.env.anchor():
            gm_pool.exchange(0, dx)
            return _spot(pool)

    lo = 0
    hi = max(1, pool.balances(0) // 1_000)
    while spot_after(hi) < target_spot:
        hi *= 2
        assert hi <= pool.balances(0) * 10, "failed to bracket +20% spot trade"

    while hi - lo > 1:
        mid = (lo + hi) // 2
        if spot_after(mid) >= target_spot:
            hi = mid
        else:
            lo = mid

    gm_pool.exchange(0, hi)
    return hi


def _stagnate_until_oracle_catches_up(pool, params, rounds=4):
    gm_pool = GodModePool(pool)
    for i in range(rounds):
        boa.env.time_travel(seconds=params["ma_time"] * 20)
        if i % 2 == 0:
            gm_pool.exchange(0, max(1, pool.balances(0) // 10**12))
        else:
            gm_pool.exchange(1, max(1, pool.balances(1) // 10**12))


def _solve_all_coin1_value_for_spot(pool, target_price_scale, target_spot):
    def spot_at(value):
        amount1 = value * WAD // target_spot
        return pool.calc_force_tweak_price([0, amount1], target_price_scale)[1]

    lo = 0
    hi = max(1, pool.balances(0) // 1_000)
    while spot_at(hi) > target_spot:
        hi *= 2
        assert hi <= pool.balances(0) * 10, "failed to bracket force-tweak value"

    while hi - lo > 1:
        mid = (lo + hi) // 2
        if spot_at(mid) <= target_spot:
            hi = mid
        else:
            lo = mid

    return hi


def _find_force_amounts(pool, target_price_scale):
    old_vp = pool.virtual_price()
    old_spot = _spot(pool)
    balances = [pool.balances(0), pool.balances(1)]
    no_amount_spot = pool.calc_force_tweak_price([0, 0], target_price_scale)[1]
    donation_coin = 1 if no_amount_spot > old_spot else 0

    def evaluate(amount):
        amounts = [0, 0]
        amounts[donation_coin] = amount
        vp, spot = pool.calc_force_tweak_price(amounts, target_price_scale)
        if vp < old_vp:
            return None
        vp_gain = vp - old_vp
        spot_diff = _rel_diff_wad(spot, old_spot)
        score = spot_diff * 10**30 + vp_gain
        return score, amounts, vp, spot, spot_diff

    def crossed(amount):
        amounts = [0, 0]
        amounts[donation_coin] = amount
        spot = pool.calc_force_tweak_price(amounts, target_price_scale)[1]
        if donation_coin == 1:
            return spot <= old_spot
        return spot >= old_spot

    lo = 0
    hi = max(1, balances[donation_coin] // 10_000)
    max_amount = balances[donation_coin] // 100
    while hi < max_amount and not crossed(hi):
        hi *= 2

    assert crossed(hi), "failed to bracket force-tweak amount"

    while hi - lo > 1:
        mid = (lo + hi) // 2
        if crossed(mid):
            hi = mid
        else:
            lo = mid

    best = None
    for amount in [max(0, lo - 1), lo, hi, hi + 1]:
        candidate = evaluate(amount)
        if candidate is not None and (best is None or candidate[0] < best[0]):
            best = candidate

    assert best is not None, "failed to find force-tweak amounts"
    assert best[4] <= FORCE_TWEAK_MAX_SPOT_DEVIATION_WAD
    return best[1]


def test_force_tweak_price_funded_teleport_preserves_spot(pool, coins):
    gm_pool = GodModePool(pool)
    gm_pool.add_liquidity_balanced(10_000_000 * WAD)

    target_price_scale = pool.price_scale() * (WAD + TARGET_GAP_WAD) // WAD
    pool.eval(f"self.cached_price_oracle = {target_price_scale}")

    amounts = _find_force_amounts(pool, target_price_scale)
    caller = boa.env.generate_address()
    for coin, amount in zip(coins, amounts):
        boa.deal(coin, caller, amount)
        coin.approve(pool, 2**256 - 1, sender=caller)

    old_state = {
        "vp": pool.virtual_price(),
        "spot": _spot(pool),
        "supply": pool.totalSupply(),
        "donations": pool.donation_shares(),
        "oracle": pool.eval("self.cached_price_oracle"),
        "last_timestamp": pool.last_timestamp(),
        "last_prices": pool.last_prices(),
    }
    out = pool.force_tweak_price(
        amounts,
        sender=caller,
    )
    assert out == target_price_scale
    assert pool.price_scale() == target_price_scale
    assert pool.virtual_price() >= old_state["vp"]
    assert _rel_diff_wad(_spot(pool), old_state["spot"]) <= FORCE_TWEAK_MAX_SPOT_DEVIATION_WAD
    assert pool.totalSupply() == old_state["supply"]
    assert pool.donation_shares() == old_state["donations"]
    assert pool.eval("self.cached_price_oracle") == old_state["oracle"]
    assert pool.last_timestamp() == old_state["last_timestamp"]
    assert pool.last_prices() == old_state["last_prices"]


def test_force_tweak_price_reverts_for_same_target(pool, coins):
    gm_pool = GodModePool(pool)
    gm_pool.add_liquidity_balanced(10_000_000 * WAD)
    pool.eval("self.cached_price_oracle = self.cached_price_scale")

    caller = boa.env.generate_address()
    amounts = [10**18, 10**18]
    for coin, amount in zip(coins, amounts):
        boa.deal(coin, caller, amount)
        coin.approve(pool, 2**256 - 1, sender=caller)

    with boa.reverts(dev='"same price scale"'):
        pool.force_tweak_price(amounts, sender=caller)


def test_force_tweak_price_reverts_when_spot_moves_too_much(pool, coins):
    gm_pool = GodModePool(pool)
    gm_pool.add_liquidity_balanced(10_000_000 * WAD)
    pool.eval(
        f"self.cached_price_oracle = self.cached_price_scale * {WAD + TARGET_GAP_WAD} // {WAD}"
    )

    caller = boa.env.generate_address()
    amounts = [10**18, 0]
    boa.deal(coins[0], caller, amounts[0])
    coins[0].approve(pool, 2**256 - 1, sender=caller)

    with boa.reverts(dev='"spot tolerance"'):
        pool.force_tweak_price(amounts, sender=caller)


def test_force_tweak_price_value_split_study(
    factory,
    factory_admin,
    coins,
    params,
    deployer,
):
    pool = POOL_DEPLOYER.at(_deploy_pool(factory, params, coins, deployer))
    pool.apply_new_parameters(
        ONE_BPS_FEE,
        ONE_BPS_FEE,
        params["fee_gamma"],
        params["adjustment_step_min"],
        params["adjustment_step_max"],
        params["ma_time"],
        sender=factory_admin,
    )

    gm_pool = GodModePool(pool)
    gm_pool.add_liquidity_balanced(10_000_000 * WAD)
    assert pool.donation_shares() == 0

    initial_spot = _spot(pool)
    target_spot = initial_spot * 120 // 100
    trade_size = _trade_spot_up_to(pool, target_spot)
    crossed_spot = _spot(pool)
    _stagnate_until_oracle_catches_up(pool, params)
    pre_force_spot = _spot(pool)
    pre_force_vp = pool.virtual_price()
    target_price_scale = pool.price_oracle()

    value = _solve_all_coin1_value_for_spot(pool, target_price_scale, pre_force_spot)

    print(
        {
            "trade_size": trade_size,
            "initial_spot": initial_spot,
            "crossed_spot": crossed_spot,
            "pre_force_spot": pre_force_spot,
            "pre_force_spot_delta_wad": _signed_rel_diff_wad(pre_force_spot, initial_spot),
            "pre_force_vp": pre_force_vp,
            "price_scale": pool.price_scale(),
            "price_oracle": pool.price_oracle(),
            "target_price_scale": target_price_scale,
            "study_value_coin0": value,
        }
    )

    for label, coin0_pct in [("0-100", 0), ("50-50", 50), ("100-0", 100)]:
        amount0 = value * coin0_pct // 100
        amount1 = (value - amount0) * WAD // pre_force_spot
        amounts = [amount0, amount1]
        vp, spot = pool.calc_force_tweak_price(amounts, target_price_scale)

        print(
            label,
            {
                "amounts": amounts,
                "value_coin0": amount0 + amount1 * pre_force_spot // WAD,
                "spot": spot,
                "spot_delta_wad": _signed_rel_diff_wad(spot, pre_force_spot),
                "vp": vp,
                "vp_delta_wad": _signed_rel_diff_wad(vp, pre_force_vp),
            },
        )

    assert crossed_spot >= target_spot
    assert pool.price_oracle() >= initial_spot * 119 // 100
