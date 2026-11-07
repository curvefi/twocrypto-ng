from boa.test import strategy
from hypothesis import given, settings


def _factory_pack_3(x):
    # Same expression as the legacy factory's _pack_3 (CurveTwocryptoFactory.vy:122).
    # The factory stays on Vyper 0.3.10 and is compiled through vvm, so boa cannot
    # call its internal functions; test_check_packed_params_on_deployment covers the
    # real factory-to-pool path through deploy_pool.
    return (x[0] << 128) | (x[1] << 64) | x[2]


@given(val=strategy("uint256[3]", max_value=10**18))
@settings(max_examples=10000, deadline=None)
def test_pack_unpack_three_integers(swap, val):
    for packed in [swap.internal._pack_3(val), _factory_pack_3(val)]:
        unpacked = swap.internal._unpack_3(packed)  # swap unpacks
        for i in range(3):
            assert unpacked[i] == val[i]


@given(val=strategy("uint256[2]", max_value=2**128 - 1))
@settings(max_examples=10000, deadline=None)
def test_pack_unpack_2_integers(swap, val):

    packed = swap.internal._pack_2(val[0], val[1])
    unpacked = swap.internal._unpack_2(packed)  # swap unpacks

    assert unpacked[0] == val[0]
    assert unpacked[1] == val[1]
