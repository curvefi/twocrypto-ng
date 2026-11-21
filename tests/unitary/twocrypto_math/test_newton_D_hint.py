"""
newton_D caps its K0_prev hint at 10**18 and ignores hints below 10**8.

K0 = 4 * x0 * x1 / D**2 is at most 1 (10**18). A larger hint starts Newton
below 2 * sqrt(x0 * x1), where it can stall at K0 = 1 + gamma and return a D
that is far too low. The v2.2.0 math did that: the third case below returned
766964988847365748892553 for a hint of 2 * 10**18.

A tiny hint makes the starting estimate 4 * x0 * x1 / K0_prev * 10**18 overflow
uint256 (for hints up to about 3.45e7 at the largest balances); the wrapped
value can again start Newton too low. Hints below 10**8 are treated as no hint.
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


TINY_HINTS = [1, 2, 8_600_000, 34_500_000, 10**8 - 1]

# the estimate overflows for these balances and a hint of 1; before the fix
# newton_D returned 336929749525051334048057846436, 4% too low
WRAP_STATE = (
    20_000_000,
    2 * 10**16,
    [219651323348806046156703916172, 131790794009283627694022349702],
)


@pytest.mark.parametrize(
    "A, gamma, x", STATES + [WRAP_STATE, (400_000, 145 * 10**12, [10**33, 10**33])]
)
def test_tiny_hint_is_ignored(math_contract, A, gamma, x):
    no_hint = math_contract.newton_D(A, gamma, x, 0)
    for hint in TINY_HINTS:
        assert math_contract.newton_D(A, gamma, x, hint) == no_hint, hint


def test_former_wrap_now_solves(math_contract):
    A, gamma, x = WRAP_STATE
    assert math_contract.newton_D(A, gamma, x, 1) == 351251163928535869388857864019


@pytest.mark.parametrize("x", [[10**33, 10**33], [10**33, 10**30], [10**24, 9 * 10**23]])
def test_smallest_used_hint_does_not_overflow(math_contract, x):
    # at 10**8 the estimate is at most 4e76 < 2**256, so nothing wraps
    no_hint = math_contract.newton_D(400_000, 145 * 10**12, x, 0)
    hinted = math_contract.newton_D(400_000, 145 * 10**12, x, 10**8)
    assert abs(hinted - no_hint) * 10**14 <= no_hint
