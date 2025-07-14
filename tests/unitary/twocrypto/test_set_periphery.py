import boa


def test_set_views_only(pool, factory_admin):
    """Test setting only views contract"""
    mock_view = boa.env.generate_address()
    pool.set_periphery(mock_view, boa.eval("empty(address)"), sender=factory_admin)
    logs = pool.get_logs()

    assert pool.view_contract() == mock_view, "View contract not set correctly"
    assert pool.math_contract() == boa.eval("empty(address)"), "Math contract should remain empty"
    assert len(logs) == 1, "Expected one log entry"
    assert type(logs[0]).__name__ == "SetPeriphery"
    assert logs[0].views == mock_view


def test_set_math_only(pool, factory_admin):
    """Test setting only math contract"""
    # Get the current view contract (set in conftest)
    current_view = pool.view_contract()

    mock_math = boa.env.generate_address()
    pool.set_periphery(boa.eval("empty(address)"), mock_math, sender=factory_admin)

    assert pool.view_contract() == current_view, "View contract should not change"
    assert pool.math_contract() == mock_math, "Math contract not set correctly"


def test_set_both_contracts(pool, factory_admin):
    """Test setting both views and math contracts"""
    mock_view = boa.env.generate_address()
    mock_math = boa.env.generate_address()
    pool.set_periphery(mock_view, mock_math, sender=factory_admin)

    assert pool.view_contract() == mock_view, "View contract not set correctly"
    assert pool.math_contract() == mock_math, "Math contract not set correctly"


def test_update_existing_contracts(pool, factory_admin):
    """Test updating already set contracts"""
    # Set initial contracts
    initial_view = boa.env.generate_address()
    initial_math = boa.env.generate_address()
    pool.set_periphery(initial_view, initial_math, sender=factory_admin)

    # Update only views
    new_view = boa.env.generate_address()
    pool.set_periphery(new_view, boa.eval("empty(address)"), sender=factory_admin)

    assert pool.view_contract() == new_view, "View contract not updated"
    assert pool.math_contract() == initial_math, "Math contract should not change"

    # Update only math
    new_math = boa.env.generate_address()
    pool.set_periphery(boa.eval("empty(address)"), new_math, sender=factory_admin)

    assert pool.view_contract() == new_view, "View contract should not change"
    assert pool.math_contract() == new_math, "Math contract not updated"


def test_revert_both_empty(pool, factory_admin):
    """Test that setting both contracts to empty reverts"""
    with boa.reverts("empty contract"):
        pool.set_periphery(
            boa.eval("empty(address)"), boa.eval("empty(address)"), sender=factory_admin
        )


def test_revert_non_admin(pool, user):
    """Test that non-admin cannot set contracts"""
    mock_view = boa.env.generate_address()
    with boa.reverts():
        pool.set_periphery(mock_view, boa.eval("empty(address)"), sender=user)
