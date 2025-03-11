import boa


def test_exchange_reverts(user, views_contract, swap_with_deposit):
    with boa.reverts():
        views_contract.get_dy(0, 2, 10**6, swap_with_deposit)

    with boa.reverts():
        views_contract.get_dy(2, 1, 10**6, swap_with_deposit)

    with boa.reverts():
        swap_with_deposit.exchange(1, 3, 10**6, 0, sender=user)

    with boa.reverts():
        swap_with_deposit.exchange(2, 2, 10**6, 0, sender=user)
