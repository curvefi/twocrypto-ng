from boa.test import strategy
from hypothesis import given, settings

from tests.utils.constants import packing_utils


@given(val=strategy("uint256[3]", max_value=10**18))
@settings(max_examples=10000, deadline=None)
def test_pack_unpack_three_integers(pool, factory, val):
    for contract in [pool, factory]:
        packed = packing_utils.internal.pack_3(val)
        unpacked = packing_utils.internal.unpack_3(packed)  # swap unpacks
        for i in range(3):
            assert unpacked[i] == val[i]


@given(val=strategy("uint256[2]", max_value=2**128 - 1))
@settings(max_examples=10000, deadline=None)
def test_pack_unpack_2_integers(pool, val):
    packed = packing_utils.internal.pack_2(val[0], val[1])
    unpacked = packing_utils.internal.unpack_2(packed)  # swap unpacks

    assert unpacked[0] == val[0]
    assert unpacked[1] == val[1]
