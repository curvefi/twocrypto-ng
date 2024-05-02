"""
Test that stragies are working correctly.
(A broken SearchStrategy would also break stateful testing.)
"""

from hypothesis import given
from strategies import pool


@given(pool=pool())
def test_swap(pool):
    """
    Make sure swap pools are initialized correctly.
    """
    pass
