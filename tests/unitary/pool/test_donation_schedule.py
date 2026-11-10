import boa
import pytest

from tests.utils.constants import PRECISION


def _trigger_burn_via_exchange(pool, ratio_num=13, ratio_den=10):
    """
    Force a rebalance using exchange until a donation burn happens.
    We set the oracle far from price_scale and then perform a few swaps to
    trigger tweak_price. Returns True if a burn occurred.
    """
    ps = pool.price_scale()
    pool.eval(f"self.cached_price_oracle = {ps * ratio_num // ratio_den}")
    pool.eval("self.last_timestamp = block.timestamp")

    pre_s = pool.donation_shares()

    # Wash trade the pool with small swaps. This touches tweak_price and pays
    # fees without depending on a near-limit imbalance to reach the donation
    # burn path.
    for k in range(100):
        dx = pool.balances(0) // 10
        pool.eval("self.last_timestamp = block.timestamp-1")
        out = pool.exchange(0, dx, update_ema=False)
        pool.eval("self.last_timestamp = block.timestamp")
        if pool.donation_shares() < pre_s:
            return True
        pool.exchange(1, out, update_ema=False)
        if pool.donation_shares() < pre_s:
            return True

    return False


def _set_protection_factor(pool, pf_num, pf_den):
    """
    Set donation protection factor to pf_num/pf_den for the next block by
    adjusting expiry relative to period. Does not change threshold.
    """
    assert 0 <= pf_num <= pf_den
    period = max(10, pool.donation_protection_period())
    pool.eval(f"self.donation_protection_expiry_ts = block.timestamp + {period * pf_num // pf_den}")


def _snapshot(pool):
    return {
        "S": pool.donation_shares(),
        "U": _read_donation_shares(pool, False),
        "A": _read_donation_shares(pool, True),
        "TS": pool.totalSupply(),
        "ts": boa.env.evm.patch.timestamp,
        "vp": pool.virtual_price(),
        "ps": pool.price_scale(),
        "D": pool.D(),
    }


def _read_donation_shares(pool, protected: bool):
    # Call the internal function via eval, with a formatted boolean literal.
    flag = "True" if protected else "False"
    return pool.eval(f"self._donation_shares({flag})")


@pytest.fixture()
def pool_ready_with_donation(gm_pool):
    # Seed liquidity and donate a visible amount (~5% of supply)
    base_liq = 1_000_000 * 10**18
    gm_pool.add_liquidity_balanced(base_liq)

    donate_usd = 50_000 * 10**18
    minted = gm_pool.donate_balanced(donate_usd)
    assert minted > 0
    assert gm_pool.donation_shares() == minted

    return gm_pool


def test_burn_occurs_and_amounts_consistent(pool_ready_with_donation):
    pool = pool_ready_with_donation

    # No protection for this test
    _set_protection_factor(pool, 0, 1)

    # Unlock roughly half
    D = pool.donation_duration()
    boa.env.time_travel(seconds=D // 2)

    pre = _snapshot(pool)
    assert pre["U"] > 0 and pre["A"] == pre["U"]

    # Trigger a price tweak (and potential burn)
    assert _trigger_burn_via_exchange(pool), "expected a donation burn to occur"

    post = _snapshot(pool)

    # Ensure burn actually happened for this setup
    assert post["S"] < pre["S"], "expected a donation burn to occur"

    B = pre["S"] - post["S"]

    # Smoke: amounts are positive and bounded
    assert B > 0
    assert post["A"] <= pre["A"]


def test_reanchor_unlocked_exact(pool_ready_with_donation):
    pool = pool_ready_with_donation

    # Keep protection off to make A == U
    _set_protection_factor(pool, 0, 1)

    # Unlock a custom fraction for deterministic math
    D = pool.donation_duration()
    boa.env.time_travel(seconds=D // 3)

    pre = _snapshot(pool)
    assert pre["U"] > 0 and pre["A"] == pre["U"]

    assert _trigger_burn_via_exchange(pool), "expected a donation burn to occur"
    post = _snapshot(pool)
    assert post["S"] < pre["S"], "expected a donation burn to occur"

    B = pre["S"] - post["S"]
    A = pre["A"]
    U = pre["U"]
    # P2. U' = U - floor(B * U / A) when A>0 (allow slight rounding slack)
    U_target = U - (B * U) // A
    assert post["U"] == pytest.approx(U_target, rel=5e-6)


def test_totals_and_virtual_price_consistency(pool_ready_with_donation):
    pool = pool_ready_with_donation

    # Small unlock and then burn
    boa.env.time_travel(seconds=pool.donation_duration() // 4)
    pre = _snapshot(pool)
    assert _trigger_burn_via_exchange(pool), "expected a donation burn to occur"
    post = _snapshot(pool)
    assert post["S"] < pre["S"], "expected a donation burn to occur"

    B = pre["S"] - post["S"]

    # P3. donation_shares' and totalSupply' shrink 1:1
    assert post["S"] == pre["S"] - B
    assert post["TS"] == pre["TS"] - B

    # virtual_price matches xcp / totalSupply with new state
    calc_vp = 10**18 * pool.internal._xcp(pool.D(), pool.price_scale()) // pool.totalSupply()
    assert post["vp"] == calc_vp


def test_time_evolution_linear_no_protection(pool_ready_with_donation):
    pool = pool_ready_with_donation

    _set_protection_factor(pool, 0, 1)
    boa.env.time_travel(seconds=pool.donation_duration() // 5)
    assert _trigger_burn_via_exchange(pool), "expected a donation burn to occur"
    snap = _snapshot(pool)

    new_total = snap["S"]
    assert new_total > 0

    # P5. After Δt, unlocked grows linearly by slope new_total / duration
    dt = pool.donation_duration() // 10
    target = min(new_total, snap["U"] + new_total * dt // pool.donation_duration())
    boa.env.time_travel(seconds=dt)
    assert abs(_read_donation_shares(pool, False) - target) <= 10


def test_extreme_burn_minimal_rounding(pool_ready_with_donation):
    pool = pool_ready_with_donation

    # No protection, tiny unlock
    _set_protection_factor(pool, 0, 1)
    boa.env.time_travel(seconds=max(1, pool.donation_duration() // 1000))

    pre = _snapshot(pool)
    assert _trigger_burn_via_exchange(pool), "expected a donation burn to occur"
    post = _snapshot(pool)
    assert post["S"] < pre["S"]

    B = pre["S"] - post["S"]
    # P7 (partial): small B still respected with 1 rounding unit on A delta
    assert pre["A"] - post["A"] <= B
    assert B - (pre["A"] - post["A"]) <= 1


def test_protection_factor_applies_exactly_without_burn(gm_pool):
    pool = gm_pool
    pool.add_liquidity_balanced(1_000_000 * 10**18)
    pool.donate_balanced(100_000 * 10**18)

    # Move to a partially unlocked state
    D = pool.donation_duration()
    boa.env.time_travel(seconds=D // 3)

    # Try multiple protection factors and assert application within +/- 10 wei
    for num, den in [(0, 1), (1, 4), (1, 2), (3, 4), (1, 1)]:
        _set_protection_factor(pool, num, den)
        U = _read_donation_shares(pool, False)
        expiry_now = pool.donation_protection_expiry_ts()
        now_ts = boa.env.evm.patch.timestamp
        pf = (
            (
                min(expiry_now - now_ts, pool.donation_protection_period())
                * PRECISION
                // pool.donation_protection_period()
            )
            if pool.donation_protection_expiry_ts() > boa.env.evm.patch.timestamp
            else 0
        )
        expected_A = U * (PRECISION - pf) // PRECISION
        actual_A = _read_donation_shares(pool, True)
        assert abs(int(actual_A) - int(expected_A)) <= 10


def test_protection_ratio_preserved_across_burn(pool_ready_with_donation):
    pool = pool_ready_with_donation

    # Set a non-zero protection so A/U is stable and < 1
    _set_protection_factor(pool, 1, 2)  # ~0.5

    # Partially unlock to ensure U>0
    boa.env.time_travel(seconds=pool.donation_duration() // 4)
    pre = _snapshot(pool)
    assert pre["U"] > 0
    # Pre ratio at PRECISION scale
    pre_ratio = pre["A"] * PRECISION // pre["U"]

    assert _trigger_burn_via_exchange(pool), "expected a donation burn to occur"
    post = _snapshot(pool)
    assert post["S"] < pre["S"]
    assert post["U"] > 0

    post_ratio = post["A"] * PRECISION // post["U"]
    # Allow tiny rounding slack of 1 wei at PRECISION scale
    assert abs(int(post_ratio) - int(pre_ratio)) <= 1
