"""
newton_D caps its K0_prev hint at 10**18.

K0 = 4 * x0 * x1 / D**2 is at most 1 (10**18). A larger hint starts Newton
below 2 * sqrt(x0 * x1), where it can stall at K0 = 1 + gamma and return a D
that is far too low. The v2.2.0 math did that: the third case below returned
766964988847365748892553 for a hint of 2 * 10**18.
"""

import pytest

STATES = [
    # A, gamma, x
    (400_000, 145 * 10**12, [10**24, 9 * 10**23]),
    (4_000, 10**10, [10**21, 10**21]),
    (20_000_000, 2 * 10**16, [5 * 10**23, 3 * 10**23]),
    (16_000_000, 10**17, [10**20, 2 * 10**19]),
]

BAD_HINTS = [10**18 + 1, 2 * 10**18, 10**19, 2**256 - 1]


@pytest.mark.parametrize("A, gamma, x", STATES)
def test_hint_above_one_is_capped(math_contract, A, gamma, x):
    capped = math_contract.newton_D(A, gamma, x, 10**18)
    for hint in BAD_HINTS:
        assert math_contract.newton_D(A, gamma, x, hint) == capped, hint


@pytest.mark.parametrize("A, gamma, x", STATES)
def test_capped_hint_gives_the_no_hint_invariant(math_contract, A, gamma, x):
    no_hint = math_contract.newton_D(A, gamma, x, 0)
    capped = math_contract.newton_D(A, gamma, x, 2 * 10**18)
    # both converge to the same root; Newton's stopping rule allows D / 10**14
    assert abs(capped - no_hint) * 10**14 <= no_hint


def test_former_stall_now_solves(math_contract):
    D = math_contract.newton_D(20_000_000, 2 * 10**16, [5 * 10**23, 3 * 10**23], 2 * 10**18)
    assert D == 799565326020707440406131
