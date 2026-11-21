import boa


def test_sender_balance_decreases(loaded_alice, bob, pool):
    sender_balance = pool.balanceOf(loaded_alice)
    amount = sender_balance // 4

    with boa.env.prank(loaded_alice):
        pool.transfer(bob, amount)

    assert pool.balanceOf(loaded_alice) == sender_balance - amount


def test_receiver_balance_increases(loaded_alice, bob, pool):
    receiver_balance = pool.balanceOf(bob)
    amount = pool.balanceOf(loaded_alice) // 4

    with boa.env.prank(loaded_alice):
        pool.transfer(bob, amount)

    assert pool.balanceOf(bob) == receiver_balance + amount


def test_total_supply_not_affected(loaded_alice, bob, pool):
    total_supply = pool.totalSupply()
    amount = pool.balanceOf(loaded_alice)

    with boa.env.prank(loaded_alice):
        pool.transfer(bob, amount)

    assert pool.totalSupply() == total_supply


def test_returns_true(loaded_alice, bob, pool):
    amount = pool.balanceOf(loaded_alice)

    with boa.env.prank(loaded_alice):
        assert pool.transfer(bob, amount)


def test_transfer_full_balance(loaded_alice, bob, pool):
    amount = pool.balanceOf(loaded_alice)
    receiver_balance = pool.balanceOf(bob)

    with boa.env.prank(loaded_alice):
        pool.transfer(bob, amount)

    assert pool.balanceOf(loaded_alice) == 0
    assert pool.balanceOf(bob) == receiver_balance + amount


def test_transfer_zero_tokens(loaded_alice, bob, pool):
    sender_balance = pool.balanceOf(loaded_alice)
    receiver_balance = pool.balanceOf(bob)

    with boa.env.prank(loaded_alice):
        pool.transfer(bob, 0)

    assert pool.balanceOf(loaded_alice) == sender_balance
    assert pool.balanceOf(bob) == receiver_balance


def test_transfer_to_self(loaded_alice, pool):
    sender_balance = pool.balanceOf(loaded_alice)
    amount = sender_balance // 4

    with boa.env.prank(loaded_alice):
        pool.transfer(loaded_alice, amount)

    assert pool.balanceOf(loaded_alice) == sender_balance


def test_insufficient_balance(loaded_alice, bob, pool):
    balance = pool.balanceOf(loaded_alice)

    with boa.reverts(), boa.env.prank(loaded_alice):
        pool.transfer(bob, balance + 1)


def test_transfer_event_fires(loaded_alice, bob, pool):
    amount = pool.balanceOf(loaded_alice)
    with boa.env.prank(loaded_alice):
        pool.transfer(bob, amount)

    logs = pool.get_logs()

    assert len(logs) == 1
    assert type(logs[0]).__name__ == "Transfer"
    assert logs[0].value == amount
    assert logs[0].sender.lower() == loaded_alice.lower()
    assert logs[0].receiver.lower() == bob.lower()
