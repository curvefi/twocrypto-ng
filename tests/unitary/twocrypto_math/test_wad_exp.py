"""
This test suit containis basic tests to prevent regressions or breaking
changes in the math library. More in depth tests are done directly in the
snekmate repository.
"""

import boa
import math


def test_default_behavior(math_contract):
    # Test e^0 = 1
    assert math_contract.wad_exp(0) == 10**18, "e^0 should be 1"

    # Test e^1 = e
    result = math_contract.wad_exp(10**18)
    expected = int(math.e * 10**18)
    # Calculate percentage difference
    percent_diff = abs(result - expected) * 100 / expected
    assert percent_diff <= 0.0000001, "e^1 should be e"


def test_overflow(math_contract):
    with boa.reverts("math: wad_exp overflow"):
        math_contract.wad_exp(135305999368893231589)


def test_underflow(math_contract):
    assert math_contract.wad_exp(-42139678854452767551) == 0
