# pragma version 0.4.3
# pragma optimize gas
"""
@title TwocryptoFee
@notice External base-fee calculator for Twocrypto pools.
@dev The caller passes the transient `xp` and packed fee params so the hook can
     reproduce the legacy balance-based fee formula from `_fee` exactly.
"""

N_COINS: constant(uint256) = 2
PRECISION: constant(uint256) = 10**18


@internal
@pure
def _unpack_3(_packed: uint256) -> uint256[3]:
    """
    @notice Unpacks a uint256 into 3 integers (values must be <= 10**18)
    @param val The uint256 to unpack
    @return uint256[3] A list of length 3 with unpacked integers
    """
    return [
        (_packed >> 128) & 18446744073709551615,
        (_packed >> 64) & 18446744073709551615,
        _packed & 18446744073709551615,
    ]


@external
@view
def get_fee(xp: uint256[N_COINS], packed_fee_params: uint256) -> uint256:
    fee_params: uint256[3] = self._unpack_3(packed_fee_params)

    # warm up variable with sum of balances
    B: uint256 = xp[0] + xp[1]

    # balance indicator that goes from 10**18 (perfect pool balance)
    # to 0 (very imbalanced, 100:1 and worse)
    B = PRECISION * N_COINS**N_COINS * xp[0] // B * xp[1] // B

    # fee_gamma * balance_term / (fee_gamma * balance_term + 1 - balance_term)
    B = fee_params[2] * B // (fee_params[2] * B // PRECISION + PRECISION - B)

    # mid_fee * B + out_fee * (1 - B)
    return (fee_params[0] * B + fee_params[1] * (PRECISION - B)) // PRECISION
