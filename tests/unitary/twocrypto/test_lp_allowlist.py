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
    pool.change_allowlist([alice], [], sender=factory_admin)

    logs = pool.get_logs()
    assert [type(log).__name__ for log in logs] == ["LPAllowlistChanged", "LPAllowlistChanged"]
    assert logs[0].user.lower() == alice.lower()
    assert logs[0].allowed is True
    assert logs[1].user.lower() == ZERO_ADDRESS.lower()
    assert logs[1].allowed is True

    minted = _premint_and_add(pool, gm_pool, alice)
    assert minted > 0


def test_non_allowlisted_address_reverts_when_enabled(pool, gm_pool, factory_admin, alice, bob):
    pool.change_allowlist([alice], [], sender=factory_admin)

    with boa.reverts("!wl"):
        _premint_and_add(pool, gm_pool, bob)


def test_remove_zero_with_empty_add_disables_whitelist(pool, gm_pool, factory_admin, alice, bob):
    pool.change_allowlist([alice], [], sender=factory_admin)

    pool.change_allowlist([], [ZERO_ADDRESS], sender=factory_admin)

    logs = pool.get_logs()
    assert type(logs[-1]).__name__ == "LPAllowlistChanged"
    assert logs[-1].user.lower() == ZERO_ADDRESS.lower()
    assert logs[-1].allowed is False

    minted = _premint_and_add(pool, gm_pool, bob)
    assert minted > 0


def test_donation_bypasses_allowlist(pool, gm_pool, factory_admin, alice, bob):
    pool.change_allowlist([alice], [], sender=factory_admin)

    seeded = _premint_and_add(pool, gm_pool, alice)
    assert seeded > 0

    donation_amounts = gm_pool.compute_balanced_amounts(50 * PRECISION)
    gm_pool.premint_amounts(donation_amounts, to=bob)
    minted = pool.add_liquidity(
        donation_amounts,
        0,
        ZERO_ADDRESS,
        True,
        sender=bob,
    )
    assert minted > 0
    assert pool.balanceOf(bob) == 0


def test_zero_address_add_does_not_enable_whitelist(pool, gm_pool, factory_admin, bob):
    pool.change_allowlist([ZERO_ADDRESS], [], sender=factory_admin)

    logs = pool.get_logs()
    assert len(logs) == 0

    minted = _premint_and_add(pool, gm_pool, bob)
    assert minted > 0
