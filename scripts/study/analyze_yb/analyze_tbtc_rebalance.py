import os
import math
import argparse
from typing import Tuple, Dict

import boa

# Load environment from .env if present
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


PRECISION = 10**18
N_COINS = 2


def require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Set {name} in environment")
    return v


def vyper_xcp(D: int, price_scale: int) -> int:
    # Matches Twocrypto._xcp implementation
    return D * PRECISION // N_COINS // math.isqrt(PRECISION * price_scale)


def compute_norm(p_oracle: int, p_scale: int) -> int:
    ratio = (p_oracle * PRECISION) // p_scale
    if ratio > PRECISION:
        return ratio - PRECISION
    else:
        return PRECISION - ratio


def unpack3(packed: int) -> Tuple[int, int, int]:
    # return (allowed_extra_profit, adjustment_step, ma_time)
    a0 = (packed >> 128) & ((1 << 64) - 1)
    a1 = (packed >> 64) & ((1 << 64) - 1)
    a2 = packed & ((1 << 64) - 1)
    return a0, a1, a2


def unpack2(packed: int) -> Tuple[int, int]:
    # returns (A, gamma), per storage layout
    return (packed >> 128) & ((1 << 128) - 1), packed & ((1 << 128) - 1)


def current_A_gamma(pool) -> Tuple[int, int]:
    # Replicates _A_gamma view
    fut_time = int(pool.future_A_gamma_time())
    A1, g1 = unpack2(int(pool.future_A_gamma()))
    now_ts = int(boa.eval("block.timestamp"))
    if now_ts < fut_time:
        init = int(pool.initial_A_gamma())
        t0 = int(pool.initial_A_gamma_time())
        t1 = fut_time - t0
        t_elapsed = now_ts - t0
        t_rem = max(0, t1 - t_elapsed)
        A0, g0 = unpack2(init)
        A = (A0 * t_rem + A1 * t_elapsed) // t1
        gamma = (g0 * t_rem + g1 * t_elapsed) // t1
        return A, gamma
    return A1, g1


def detect_stable_symbol(c0_sym: str, c1_sym: str) -> int:
    # For these pools, coin0 is always stable, coin1 is BTC
    return 0


def donation_available_now(pool, now_ts: int) -> int:
    total = int(pool.donation_shares())
    dur = int(pool.donation_duration())
    last_rel = int(pool.last_donation_release_ts())
    expiry = int(pool.donation_protection_expiry_ts())
    period = int(pool.donation_protection_period())

    if dur <= 0 or total == 0:
        unlocked = 0
    else:
        elapsed = max(0, now_ts - last_rel)
        unlocked = min(total, (total * elapsed) // dur)

    if expiry > now_ts and period > 0:
        protection = min(((expiry - now_ts) * PRECISION) // period, PRECISION)
    else:
        protection = 0

    available = (unlocked * (PRECISION - protection)) // PRECISION
    return available


def analyze(pool_addr: str, time_travel_sec: int = 0) -> Dict:
    etherscan_api_key = require_env("ETHERSCAN_API_KEY")

    pool = boa.from_etherscan(pool_addr, api_key=etherscan_api_key)

    c0_addr = pool.coins(0)
    c1_addr = pool.coins(1)
    c0 = boa.from_etherscan(c0_addr, api_key=etherscan_api_key)
    c1 = boa.from_etherscan(c1_addr, api_key=etherscan_api_key)
    sym0, sym1 = c0.symbol(), c1.symbol()
    dec0, dec1 = int(c0.decimals()), int(c1.decimals())

    # Optional EMA warm-up via time travel
    if time_travel_sec > 0:
        boa.env.time_travel(seconds=time_travel_sec)

    # Read current metrics
    p_scale = int(pool.price_scale())
    p_oracle = int(pool.price_oracle())
    norm = compute_norm(p_oracle, p_scale)
    allowed, adj_step, _ = unpack3(int(pool.packed_rebalancing_params()))
    step = max(adj_step, norm // 5)

    D = int(pool.D())
    TS = int(pool.totalSupply())
    xcp = vyper_xcp(D, p_scale)
    xprof = int(pool.xcp_profit())
    threshold_vp = max(PRECISION, (xprof + PRECISION) // 2)

    # Gate 1: vp_boosted > threshold_vp + allowed
    target = threshold_vp + allowed
    A = PRECISION * xcp  # 1e18 * xcp
    # floor(A/L) > target => L <= floor(A / (target+1))
    L_max = A // (target + 1) if target + 1 > 0 else 0
    L_max = min(L_max, TS)
    donation_needed_gate1 = max(0, TS - L_max)

    now_ts = int(boa.eval("block.timestamp"))
    avail_now = donation_available_now(pool, now_ts)
    locked_supply_now = TS - avail_now
    vp_boosted_now = (PRECISION * xcp) // locked_supply_now if locked_supply_now > 0 else 0
    gate1_ok = vp_boosted_now > target

    # Step feasibility
    step_ok = norm > step

    # Post-step p_new and burn needed to maintain vp >= goal
    burn_needed = None
    vp_new_no_burn = None
    p_new = None
    if step_ok:
        p_new = (p_scale * (norm - step) + step * p_oracle) // norm

        # xp balances scaled with precisions and p_new for coin1
        b0 = int(pool.balances(0))
        b1 = int(pool.balances(1))
        p0 = 10 ** (18 - dec0)
        p1 = 10 ** (18 - dec1)
        xp0 = b0 * p0
        xp1 = b1 * p1 * p_new // PRECISION

        A_, gamma_ = current_A_gamma(pool)
        mathc = boa.from_etherscan(pool.MATH(), api_key=etherscan_api_key)
        new_D = int(mathc.newton_D(A_, gamma_, [xp0, xp1], 0))
        new_xcp = vyper_xcp(new_D, p_new)
        vp_new_no_burn = (PRECISION * new_xcp) // TS

        vp_pre = int(pool.virtual_price())
        goal_vp = max(threshold_vp, vp_pre)
        if vp_new_no_burn < goal_vp:
            tweaked_supply = (PRECISION * new_xcp) // goal_vp
            burn_needed = TS - tweaked_supply if tweaked_supply < TS else 0
        else:
            burn_needed = 0

    return {
        "pool": pool.address,
        "coin0": {"address": c0.address, "symbol": sym0, "decimals": dec0},
        "coin1": {"address": c1.address, "symbol": sym1, "decimals": dec1},
        "price_scale": p_scale,
        "price_oracle": p_oracle,
        "norm": norm,
        "adjustment_step_param": adj_step,
        "step": step,
        "allowed_extra_profit": allowed,
        "D": D,
        "totalSupply": TS,
        "xcp": xcp,
        "xcp_profit": xprof,
        "threshold_vp": threshold_vp,
        "gate1": {
            "target": target,
            "donation_needed_available": donation_needed_gate1,
            "available_now": avail_now,
            "locked_supply_now": locked_supply_now,
            "vp_boosted_now": vp_boosted_now,
            "ok": gate1_ok,
        },
        "post_step": {
            "step_ok": step_ok,
            "p_new": p_new,
            "vp_new_no_burn": vp_new_no_burn,
            "burn_needed": burn_needed,
            "burn_feasible_now": None if burn_needed is None else (burn_needed <= avail_now),
        },
    }


def simulate_swap_then_analyze(pool_addr: str, btc_amount: float) -> Dict:
    """Perform an on-fork BTC->stable swap of size `btc_amount` (in BTC units),
    then return before/after analytics and whether price_scale changed."""
    etherscan_api_key = require_env("ETHERSCAN_API_KEY")

    pool = boa.from_etherscan(pool_addr, api_key=etherscan_api_key)
    c0_addr = pool.coins(0)
    c1_addr = pool.coins(1)  # BTC
    c1 = boa.from_etherscan(c1_addr, api_key=etherscan_api_key)
    dec1 = int(c1.decimals())

    before = analyze(pool_addr, 0)

    # Mint BTC to EOA and swap BTC->stable (1 -> 0)
    dx = int(round(btc_amount * (10**dec1)))
    boa.deal(c1, boa.env.eoa, dx)
    c1.approve(pool, dx, sender=boa.env.eoa)

    ps_before = int(pool.price_scale())
    dy = int(pool.exchange(1, 0, dx, 0, sender=boa.env.eoa))
    ps_after = int(pool.price_scale())

    after = analyze(pool_addr, 0)

    return {
        "btc_amount": btc_amount,
        "dx": dx,
        "dy": dy,
        "price_scale_before": ps_before,
        "price_scale_after": ps_after,
        "tweaked": ps_after != ps_before,
        "before": before,
        "after": after,
    }


def min_seconds_to_rebalance(pool_addr: str, max_days: int = 180) -> int | None:
    """Binary search minimal dt such that both gates pass:
    - vp_boosted(dt) > threshold_vp(dt) + allowed
    - burn_needed_after_step(dt) <= available(dt)
    Uses view-only time travel (no trades)."""
    etherscan_api_key = require_env("ETHERSCAN_API_KEY")
    pool = boa.from_etherscan(pool_addr, api_key=etherscan_api_key)

    def eval_at(dt: int) -> Tuple[bool, int, int, int]:
        with boa.env.anchor():
            if dt > 0:
                boa.env.time_travel(seconds=dt)
            snap = analyze(pool_addr, 0)
            gate1 = snap["gate1"]["ok"]
            post = snap["post_step"]
            burn_needed = post["burn_needed"] if post["step_ok"] else None
            avail = snap["gate1"]["available_now"]
            ok = gate1 and post["step_ok"] and (burn_needed is not None) and (burn_needed <= avail)
            return ok, snap["norm"], post["p_new"] or 0, burn_needed or 0

    # Check now
    ok_now, _, _, _ = eval_at(0)
    if ok_now:
        return 0
    lo, hi = 0, max_days * 86400
    ok_hi, _, _, _ = eval_at(hi)
    if not ok_hi:
        return None
    while lo + 60 < hi:  # 1-minute precision
        mid = (lo + hi) // 2
        ok_mid, _, _, _ = eval_at(mid)
        if ok_mid:
            hi = mid
        else:
            lo = mid
    return hi


def main():
    parser = argparse.ArgumentParser(description="Analyze tBTC TwoCrypto rebalance conditions")
    parser.add_argument(
        "--pool",
        dest="pool",
        default=os.environ.get("YB_TBTC_POOL", "0xf1F435B05D255a5dBdE37333C0f61DA6F69c6127"),
        help="Pool address (default: env YB_TBTC_POOL or known tBTC)",
    )
    parser.add_argument(
        "--time-travel",
        dest="time_travel",
        type=int,
        default=0,
        help="Seconds to time-travel before reading metrics (EMA warm-up)",
    )
    parser.add_argument(
        "--swap-btc",
        dest="swap_btc",
        type=float,
        default=None,
        help="If set, perform a BTC->stable swap of this many BTC before analysis",
    )
    args = parser.parse_args()

    rpc = require_env("WEB3_PROVIDER_URL")
    # prefer new API to avoid deprecation warning
    boa.fork(rpc)
    boa.env.eoa = boa.env.generate_address()

    res = analyze(args.pool, time_travel_sec=args.time_travel)

    # Pretty print compact summary
    gate1 = res["gate1"]
    post = res["post_step"]
    print("Pool:", res["pool"])
    print("price_scale:", res["price_scale"], "price_oracle:", res["price_oracle"])
    print("norm:", res["norm"], "step:", res["step"], "allowed:", res["allowed_extra_profit"])
    print("threshold_vp:", res["threshold_vp"])
    print(
        "Gate1: donation_needed_available=",
        gate1["donation_needed_available"],
        "available_now=",
        gate1["available_now"],
        "ok=",
        gate1["ok"],
    )
    if post["p_new"] is not None:
        print("Post-step: p_new=", post["p_new"], "vp_new_no_burn=", post["vp_new_no_burn"])
        print("burn_needed=", post["burn_needed"], "burn_feasible_now=", post["burn_feasible_now"])
    else:
        print("Post-step: step condition not met (norm<=step)")

    # Optional: simulate BTC swap
    if args.swap_btc is not None and args.swap_btc > 0:
        sim = simulate_swap_then_analyze(res["pool"], args.swap_btc)
        print("\nSimulated BTC swap:")
        print("btc_amount=", sim["btc_amount"], "dx=", sim["dx"], "dy=", sim["dy"])
        print(
            "price_scale:",
            sim["price_scale_before"],
            "->",
            sim["price_scale_after"],
            "tweaked=",
            sim["tweaked"],
        )
        post = sim["after"]["post_step"]
        print(
            "after.post_step: step_ok=",
            post["step_ok"],
            "p_new=",
            post["p_new"],
            "burn_needed=",
            post["burn_needed"],
            "feasible=",
            post["burn_feasible_now"],
        )

    # Optional: search minimal dt to pass both gates
    dt = min_seconds_to_rebalance(res["pool"])
    print("min_seconds_to_rebalance:", dt)


if __name__ == "__main__":
    main()
