import boa


def test_revert_unauthorised_access(user, factory):
    with boa.env.prank(user):
        with boa.reverts("admin only"):
            factory.set_pool_implementation(boa.env.generate_address(), 0)

        with boa.reverts("admin only"):
            factory.set_gauge_implementation(boa.env.generate_address())

        with boa.reverts("admin only"):
            factory.set_views_implementation(boa.env.generate_address())


def test_revert_unauthorised_set_fee_receiver(user, factory, fee_receiver):
    with boa.env.prank(user):
        with boa.reverts("admin only"):
            factory.set_fee_receiver(user)

    assert factory.fee_receiver() == fee_receiver


def test_revert_unauthorised_new_admin(user, factory, owner):
    with boa.env.prank(user), boa.reverts("admin only"):
        factory.commit_transfer_ownership(user)

    with boa.env.prank(owner):
        factory.commit_transfer_ownership(boa.env.generate_address())

    with boa.env.prank(user), boa.reverts("future admin only"):
        factory.accept_transfer_ownership()
