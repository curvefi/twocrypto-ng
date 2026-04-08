import boa

PRECISION = 10**18
INITIAL_LIQUIDITY = 1000 * PRECISION
ZERO_ADDRESS = boa.eval("empty(address)")


def _premint_and_add(pool, gm_pool, account, donation=False):
    amounts = gm_pool.compute_balanced_amounts(INITIAL_LIQUIDITY)
    gm_pool.premint_amounts(amounts, to=account)
    return pool.add_liquidity(
        amounts,
        0,
        ZERO_ADDRESS if donation else account,
        donation,
        sender=account,
    )


def test_change_allowlist_only_admin(pool, alice):
    with boa.reverts("only owner"):
        pool.change_allowlist([alice], [], sender=alice)


def test_add_enables_whitelist_and_allows_added_address(pool, gm_pool, factory_admin, alice):
    assert pool.lp_allowlist(ZERO_ADDRESS) is False

    pool.change_allowlist([alice], [], sender=factory_admin)

    assert pool.lp_allowlist(ZERO_ADDRESS) is True
    assert pool.lp_allowlist(alice) is True

    minted = _premint_and_add(pool, gm_pool, alice)
    assert minted > 0


def test_non_allowlisted_address_reverts_when_enabled(pool, gm_pool, factory_admin, alice, bob):
    pool.change_allowlist([alice], [], sender=factory_admin)

    with boa.reverts("!wl"):
        _premint_and_add(pool, gm_pool, bob)


def test_remove_zero_with_empty_add_disables_whitelist(pool, gm_pool, factory_admin, alice, bob):
    pool.change_allowlist([alice], [], sender=factory_admin)
    assert pool.lp_allowlist(ZERO_ADDRESS) is True

    pool.change_allowlist([], [ZERO_ADDRESS], sender=factory_admin)

    assert pool.lp_allowlist(ZERO_ADDRESS) is False

    minted = _premint_and_add(pool, gm_pool, bob)
    assert minted > 0


def test_donation_bypasses_allowlist(pool, gm_pool, factory_admin, alice, bob):
    pool.change_allowlist([alice], [], sender=factory_admin)

    minted = _premint_and_add(pool, gm_pool, bob, donation=True)
    assert minted > 0
    assert pool.balanceOf(bob) == 0
