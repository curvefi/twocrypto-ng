import boa


def test_default_behavior(pool, factory_admin):
    mock_view = boa.env.generate_address()
    pool.set_views(mock_view, sender=factory_admin)
    logs = pool.get_logs()

    assert pool.view_contract() == mock_view, "View contract not set correctly"
    assert len(logs) == 1, "Expected one log entry"
    assert type(logs[0]).__name__ == "SetViews"
    assert logs[0].views == mock_view
