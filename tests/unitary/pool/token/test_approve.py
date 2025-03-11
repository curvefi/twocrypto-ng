import boa
import pytest


@pytest.mark.parametrize("idx", range(5))
def test_initial_approval_is_zero(swap, alice, users, idx):
    assert swap.allowance(alice, users[idx]) == 0


def test_approve(swap, alice, bob):
    with boa.env.prank(alice):
        swap.approve(bob, 10**19)

    assert swap.allowance(alice, bob) == 10**19


def test_modify_approve_zero_nonzero(swap, alice, bob):
    with boa.env.prank(alice):
        swap.approve(bob, 10**19)
        swap.approve(bob, 0)
        swap.approve(bob, 12345678)

    assert swap.allowance(alice, bob) == 12345678


def test_revoke_approve(swap, alice, bob):
    with boa.env.prank(alice):
        swap.approve(bob, 10**19)
        swap.approve(bob, 0)

    assert swap.allowance(alice, bob) == 0


def test_approve_self(swap, alice):
    with boa.env.prank(alice):
        swap.approve(alice, 10**19)

    assert swap.allowance(alice, alice) == 10**19


def test_only_affects_target(swap, alice, bob):
    with boa.env.prank(alice):
        swap.approve(bob, 10**19)

    assert swap.allowance(bob, alice) == 0


def test_returns_true(swap, alice, bob):
    with boa.env.prank(alice):
        assert swap.approve(bob, 10**19)


def test_approval_event_fires(swap, alice, bob):
    with boa.env.prank(alice):
        swap.approve(bob, 10**19)

    logs = swap.get_logs()

    assert len(logs) == 1
    assert type(logs[0]).__name__ == "Approval"
    assert logs[0].owner.lower() == alice.lower()
    assert logs[0].spender.lower() == bob.lower()
    assert logs[0].value == 10**19


def test_infinite_approval(swap, alice, bob):
    with boa.env.prank(alice):
        swap.approve(bob, 2**256 - 1)

    boa.deal(swap, alice, 10**18)
    with boa.env.prank(bob):
        swap.transferFrom(alice, bob, 10**18)

    assert swap.allowance(alice, bob) == 2**256 - 1
