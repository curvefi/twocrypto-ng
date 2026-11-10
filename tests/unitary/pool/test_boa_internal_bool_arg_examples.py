"""
Single demo test for boa devs, showing a boolean argument misbinding on
internal calls and how to reproduce/fix it.

How to run and see prints:

  uv run pytest -s tests/unitary/pool/test_boa_internal_bool_arg_examples.py::test_boa_internal_bool_arg_demo

This test is marked xfail because it demonstrates a mismatch between an
internal call and an eval-based call when passing True to a boolean arg.
"""

import boa
import pytest


def _set_protection_factor(pool, pf_num: int, pf_den: int):
    assert 0 <= pf_num <= pf_den
    period = max(10, pool.donation_protection_period())
    pool.eval(f"self.donation_protection_expiry_ts = block.timestamp + {period * pf_num // pf_den}")


@pytest.mark.xfail(
    reason=(
        "Demonstrates boa internal-call bool arg quirk: _donation_shares(True) "
        "may ignore protection and return the unprotected value"
    )
)
def test_boa_internal_bool_arg_demo(gm_pool):
    pool = gm_pool

    print("\n--- Repro guide ---")
    print("1) Seed pool and donate")
    print("2) Partially unlock (time travel)")
    print("3) Set PF=1 for this block")
    print("4) Compare _donation_shares(False) and (True) via internal vs eval")
    print("   Expect: False matches; True mismatches (this test xfails)")
    print(
        "Command: uv run pytest -s tests/unitary/pool/test_boa_internal_bool_arg_examples.py::test_boa_internal_bool_arg_demo"
    )

    # 1) Seed pool and donate
    pool.add_liquidity_balanced(1_000_000 * 10**18)
    pool.donate_balanced(100_000 * 10**18)

    # 2) Partially unlock
    boa.env.time_travel(seconds=pool.donation_duration() // 3)

    # 3) PF = 1 for this block (full protection)
    _set_protection_factor(pool, 1, 1)

    # Ground truth protected/unprotected via eval
    U_eval = pool.eval("self._donation_shares(False)")
    A_eval = pool.eval("self._donation_shares(True)")

    # Internal stub calls
    U_internal = pool.internal._donation_shares(False)
    A_internal = pool.internal._donation_shares(True)

    print(f"U_internal={U_internal}")
    print(f"U_eval    ={U_eval}")
    print(f"A_internal={A_internal}")
    print(f"A_eval    ={A_eval}")

    # Sanity: False path is consistent and > 0
    assert U_internal == U_eval
    assert U_internal > 0

    # With PF=1 protected value should be 0; internal(True) may ignore PF
    expected_A = 0
    print(f"expected_A={expected_A}")

    # Intentional: demonstrate mismatch by asserting equality (xfail)
    assert A_internal == expected_A
