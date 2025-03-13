import boa
import pytest


@pytest.mark.parametrize("idx", range(5))
def test_initial_approval_is_zero(pool, alice, users, idx):
    assert pool.allowance(alice, users[idx]) == 0


def test_approve(pool, alice, bob):
    with boa.env.prank(alice):
        pool.approve(bob, 10**19)

    assert pool.allowance(alice, bob) == 10**19


def test_modify_approve_zero_nonzero(pool, alice, bob):
    with boa.env.prank(alice):
        pool.approve(bob, 10**19)
        pool.approve(bob, 0)
        pool.approve(bob, 12345678)

    assert pool.allowance(alice, bob) == 12345678


def test_revoke_approve(pool, alice, bob):
    with boa.env.prank(alice):
        pool.approve(bob, 10**19)
        pool.approve(bob, 0)

    assert pool.allowance(alice, bob) == 0


def test_approve_self(pool, alice):
    with boa.env.prank(alice):
        pool.approve(alice, 10**19)

    assert pool.allowance(alice, alice) == 10**19


def test_only_affects_target(pool, alice, bob):
    with boa.env.prank(alice):
        pool.approve(bob, 10**19)

    assert pool.allowance(bob, alice) == 0


def test_returns_true(pool, alice, bob):
    with boa.env.prank(alice):
        assert pool.approve(bob, 10**19)


def test_approval_event_fires(pool, alice, bob):
    with boa.env.prank(alice):
        pool.approve(bob, 10**19)

    logs = pool.get_logs()

    assert len(logs) == 1
    assert type(logs[0]).__name__ == "Approval"
    assert logs[0].owner.lower() == alice.lower()
    assert logs[0].spender.lower() == bob.lower()
    assert logs[0].value == 10**19


def test_infinite_approval(pool, alice, bob):
    with boa.env.prank(alice):
        pool.approve(bob, 2**256 - 1)

    boa.deal(pool, alice, 10**18)
    with boa.env.prank(bob):
        pool.transferFrom(alice, bob, 10**18)

    assert pool.allowance(alice, bob) == 2**256 - 1
