import boa


def test_sender_balance_decreases(loaded_alice, bob, charlie, pool):
    sender_balance = pool.balanceOf(loaded_alice)
    amount = sender_balance // 4

    with boa.env.prank(loaded_alice):
        pool.approve(bob, amount)

    with boa.env.prank(bob):
        pool.transferFrom(loaded_alice, charlie, amount)

    assert pool.balanceOf(loaded_alice) == sender_balance - amount


def test_receiver_balance_increases(loaded_alice, bob, charlie, pool):
    receiver_balance = pool.balanceOf(charlie)
    amount = pool.balanceOf(loaded_alice) // 4

    with boa.env.prank(loaded_alice):
        pool.approve(bob, amount)

    with boa.env.prank(bob):
        pool.transferFrom(loaded_alice, charlie, amount)

    assert pool.balanceOf(charlie) == receiver_balance + amount


def test_caller_balance_not_affected(loaded_alice, bob, charlie, pool):
    caller_balance = pool.balanceOf(bob)
    amount = pool.balanceOf(loaded_alice)

    with boa.env.prank(loaded_alice):
        pool.approve(bob, amount)

    with boa.env.prank(bob):
        pool.transferFrom(loaded_alice, charlie, amount)

    assert pool.balanceOf(bob) == caller_balance


def test_caller_approval_affected(alice, bob, charlie, pool):
    approval_amount = pool.balanceOf(alice)
    transfer_amount = approval_amount // 4

    with boa.env.prank(alice):
        pool.approve(bob, approval_amount)

    with boa.env.prank(bob):
        pool.transferFrom(alice, charlie, transfer_amount)

    assert pool.allowance(alice, bob) == approval_amount - transfer_amount


def test_receiver_approval_not_affected(loaded_alice, bob, charlie, pool):
    approval_amount = pool.balanceOf(loaded_alice)
    transfer_amount = approval_amount // 4

    with boa.env.prank(loaded_alice):
        pool.approve(bob, approval_amount)
        pool.approve(charlie, approval_amount)

    with boa.env.prank(bob):
        pool.transferFrom(loaded_alice, charlie, transfer_amount)

    assert pool.allowance(loaded_alice, charlie) == approval_amount


def test_total_supply_not_affected(loaded_alice, bob, charlie, pool):
    total_supply = pool.totalSupply()
    amount = pool.balanceOf(loaded_alice)

    with boa.env.prank(loaded_alice):
        pool.approve(bob, amount)

    with boa.env.prank(bob):
        pool.transferFrom(loaded_alice, charlie, amount)

    assert pool.totalSupply() == total_supply


def test_returns_true(loaded_alice, bob, charlie, pool):
    amount = pool.balanceOf(loaded_alice)
    with boa.env.prank(loaded_alice):
        pool.approve(bob, amount)

    with boa.env.prank(bob):
        assert pool.transferFrom(loaded_alice, charlie, amount)


def test_transfer_full_balance(loaded_alice, bob, charlie, pool):
    amount = pool.balanceOf(loaded_alice)
    receiver_balance = pool.balanceOf(charlie)

    with boa.env.prank(loaded_alice):
        pool.approve(bob, amount)

    with boa.env.prank(bob):
        pool.transferFrom(loaded_alice, charlie, amount)

    assert pool.balanceOf(loaded_alice) == 0
    assert pool.balanceOf(charlie) == receiver_balance + amount


def test_transfer_zero_tokens(loaded_alice, bob, charlie, pool):
    sender_balance = pool.balanceOf(loaded_alice)
    receiver_balance = pool.balanceOf(charlie)

    with boa.env.prank(loaded_alice):
        pool.approve(bob, sender_balance)

    with boa.env.prank(bob):
        pool.transferFrom(loaded_alice, charlie, 0)

    assert pool.balanceOf(loaded_alice) == sender_balance
    assert pool.balanceOf(charlie) == receiver_balance


def test_transfer_zero_tokens_without_approval(loaded_alice, bob, charlie, pool):
    sender_balance = pool.balanceOf(loaded_alice)
    receiver_balance = pool.balanceOf(charlie)

    with boa.env.prank(bob):
        pool.transferFrom(loaded_alice, charlie, 0)

    assert pool.balanceOf(loaded_alice) == sender_balance
    assert pool.balanceOf(charlie) == receiver_balance


def test_insufficient_balance(loaded_alice, bob, charlie, pool):
    balance = pool.balanceOf(loaded_alice)

    with boa.env.prank(loaded_alice):
        pool.approve(bob, balance + 1)

    with boa.reverts(), boa.env.prank(bob):
        pool.transferFrom(loaded_alice, charlie, balance + 1)


def test_insufficient_approval(loaded_alice, bob, charlie, pool):
    balance = pool.balanceOf(loaded_alice)

    with boa.env.prank(loaded_alice):
        pool.approve(bob, balance - 1)

    with boa.reverts(), boa.env.prank(bob):
        pool.transferFrom(loaded_alice, charlie, balance)


def test_no_approval(loaded_alice, bob, charlie, pool):
    balance = pool.balanceOf(loaded_alice)

    with boa.reverts(), boa.env.prank(bob):
        pool.transferFrom(loaded_alice, charlie, balance)


def test_revoked_approval(loaded_alice, bob, charlie, pool):
    balance = pool.balanceOf(loaded_alice)

    with boa.env.prank(loaded_alice):
        pool.approve(bob, balance)
        pool.approve(bob, 0)

    with boa.reverts(), boa.env.prank(bob):
        pool.transferFrom(loaded_alice, charlie, balance)


def test_transfer_to_self(loaded_alice, pool):
    sender_balance = pool.balanceOf(loaded_alice)
    amount = sender_balance // 4

    with boa.env.prank(loaded_alice):
        pool.approve(loaded_alice, sender_balance)
        pool.transferFrom(loaded_alice, loaded_alice, amount)

    assert pool.balanceOf(loaded_alice) == sender_balance
    assert pool.allowance(loaded_alice, loaded_alice) == sender_balance - amount


def test_transfer_to_self_no_approval(loaded_alice, pool):
    amount = pool.balanceOf(loaded_alice)

    with boa.reverts(), boa.env.prank(loaded_alice):
        pool.transferFrom(loaded_alice, loaded_alice, amount)


def test_transfer_event_fires(loaded_alice, bob, charlie, pool):
    amount = pool.balanceOf(loaded_alice)

    with boa.env.prank(loaded_alice):
        pool.approve(bob, amount)

    with boa.env.prank(bob):
        pool.transferFrom(loaded_alice, charlie, amount)

    logs = pool.get_logs()

    assert len(logs) == 2
    assert type(logs[0]).__name__ == "Approval"
    assert logs[0].value == 0  # since everything got transferred
    assert logs[0].owner.lower() == loaded_alice.lower()
    assert logs[0].spender.lower() == bob.lower()

    assert type(logs[1]).__name__ == "Transfer"
    assert logs[1].value == amount
    assert logs[1].sender.lower() == loaded_alice.lower()
    assert logs[1].receiver.lower() == charlie.lower()
