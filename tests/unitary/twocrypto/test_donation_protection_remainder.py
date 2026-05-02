import boa

from tests.utils.constants import FACTORY_DEPLOYER, PRECISION


BASE_LIQUIDITY = 1_000_000 * PRECISION
BASE_DONATION = 50_000 * PRECISION


def _remainder(pool):
    return pool.eval("self.donation_protection_extension_remainder")


def _seed_with_donation(gm_pool):
    gm_pool.add_liquidity_balanced(BASE_LIQUIDITY)
    donation_shares = gm_pool.donate_balanced(BASE_DONATION)
    assert donation_shares > 0
    assert gm_pool.donation_shares() == donation_shares


def _raw_extension_for_minted(pool, minted, old_supply):
    relative_lp_add = minted * PRECISION // (old_supply + minted)
    return relative_lp_add * pool.donation_protection_period()


def _raw_extension_for_amount(gm_pool, coin0_amount):
    pool = gm_pool.instance
    old_supply = pool.totalSupply()
    minted = pool.calc_token_amount(gm_pool.compute_balanced_amounts(coin0_amount), True)
    if minted == 0:
        return 0
    return _raw_extension_for_minted(pool, minted, old_supply)


def _amount_for_raw_extension(gm_pool, target_raw):
    pool = gm_pool.instance
    period = pool.donation_protection_period()
    target_relative = max(1, target_raw // period)
    approx = target_relative * pool.totalSupply() // (PRECISION - target_relative)
    lo = max(1, approx // 2)
    hi = max(2, approx * 2)

    while _raw_extension_for_amount(gm_pool, lo) > target_raw:
        hi = lo
        next_lo = max(1, lo // 2)
        if next_lo == lo:
            break
        lo = next_lo

    while _raw_extension_for_amount(gm_pool, hi) <= target_raw:
        lo = hi
        hi *= 2

    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if _raw_extension_for_amount(gm_pool, mid) <= target_raw:
            lo = mid
        else:
            hi = mid

    raw_extension = _raw_extension_for_amount(gm_pool, lo)
    assert 0 < raw_extension <= target_raw
    assert raw_extension < pool.donation_protection_lp_threshold()
    return lo


def _add_balanced_and_get_raw(gm_pool, coin0_amount):
    pool = gm_pool.instance
    old_supply = pool.totalSupply()
    minted = gm_pool.add_liquidity(gm_pool.compute_balanced_amounts(coin0_amount))
    raw_extension = _raw_extension_for_minted(pool, minted, old_supply)
    assert raw_extension // pool.donation_protection_lp_threshold() == 0
    return raw_extension


def test_default_donation_protection_params(pool):
    assert pool.donation_protection_period() == 600
    assert pool.donation_protection_lp_threshold() == 20 * PRECISION // 100


def test_subsecond_liquidity_adds_accumulate_into_whole_second(gm_pool):
    with boa.env.anchor():
        _seed_with_donation(gm_pool)
        pool = gm_pool.instance
        start_ts = boa.env.evm.patch.timestamp
        target_raw = pool.donation_protection_lp_threshold() // 4

        chunks = 0
        for _ in range(6):
            amount = _amount_for_raw_extension(gm_pool, target_raw)
            raw_extension = _add_balanced_and_get_raw(gm_pool, amount)
            assert raw_extension // pool.donation_protection_lp_threshold() == 0
            chunks += 1
            if pool.donation_protection_expiry_ts() > start_ts:
                break

        assert chunks > 1
        assert pool.donation_protection_expiry_ts() >= start_ts + 1
        assert _remainder(pool) < pool.donation_protection_lp_threshold()


def test_split_adds_match_aggregate_extension_within_one_second(gm_pool):
    with boa.env.anchor():
        _seed_with_donation(gm_pool)
        pool = gm_pool.instance
        chunk_amount = _amount_for_raw_extension(
            gm_pool, pool.donation_protection_lp_threshold() // 5
        )
        chunks = 9

        with boa.env.anchor():
            start_ts = boa.env.evm.patch.timestamp
            gm_pool.add_liquidity(gm_pool.compute_balanced_amounts(chunk_amount * chunks))
            aggregate_delta = pool.donation_protection_expiry_ts() - start_ts

        with boa.env.anchor():
            start_ts = boa.env.evm.patch.timestamp
            for _ in range(chunks):
                gm_pool.add_liquidity(gm_pool.compute_balanced_amounts(chunk_amount))
            split_delta = pool.donation_protection_expiry_ts() - start_ts

        assert abs(int(split_delta) - int(aggregate_delta)) <= 1


def test_capped_protection_drops_fractional_remainder(gm_pool):
    with boa.env.anchor():
        _seed_with_donation(gm_pool)
        pool = gm_pool.instance
        period = pool.donation_protection_period()
        threshold = pool.donation_protection_lp_threshold()

        pool.eval(f"self.donation_protection_expiry_ts = block.timestamp + {period}")
        pool.eval(f"self.donation_protection_extension_remainder = {threshold - 1}")

        amount = _amount_for_raw_extension(gm_pool, threshold // 4)
        _add_balanced_and_get_raw(gm_pool, amount)

        assert pool.donation_protection_expiry_ts() == boa.env.evm.patch.timestamp + period
        assert _remainder(pool) == 0


def test_set_donation_parameters_resets_fractional_remainder(gm_pool):
    with boa.env.anchor():
        _seed_with_donation(gm_pool)
        pool = gm_pool.instance
        threshold = pool.donation_protection_lp_threshold()
        now_ts = boa.env.evm.patch.timestamp

        amount = _amount_for_raw_extension(gm_pool, threshold - 1)
        _add_balanced_and_get_raw(gm_pool, amount)
        assert pool.donation_protection_expiry_ts() == now_ts
        assert _remainder(pool) > threshold * 99 // 100

        admin = FACTORY_DEPLOYER.at(pool.factory()).admin()
        new_threshold = threshold // 2
        pool.set_donation_parameters(
            pool.donation_duration(),
            pool.donation_protection_period() // 2,
            new_threshold,
            pool.donation_shares_max_ratio(),
            sender=admin,
        )
        assert _remainder(pool) == 0

        amount = _amount_for_raw_extension(gm_pool, new_threshold // 100)
        raw_extension = _add_balanced_and_get_raw(gm_pool, amount)
        assert pool.donation_protection_expiry_ts() == now_ts
        assert _remainder(pool) == raw_extension
