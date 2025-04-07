# pragma version 0.4.1

"""
@notice A stateless module to pack and unpack integers into a single uint256.
"""

@internal
@pure
def pack_3(x: uint256[3]) -> uint256:
    """
    @notice Packs 3 integers with values <= 2**64-1 into a uint256
    @param x The uint256[3] to pack
    @return uint256 Integer with packed values
    """
    return (x[0] << 128) | (x[1] << 64) | x[2]


@internal
@pure
def unpack_3(_packed: uint256) -> uint256[3]:
    """
    @notice Unpacks a uint256 into 3 integers
    @param _packed The uint256 to unpack
    @return uint256[3] A list of length 3 with unpacked integers
    """
    return [
        (_packed >> 128) & 18446744073709551615,
        (_packed >> 64) & 18446744073709551615,
        _packed & 18446744073709551615,
    ]


@pure
@internal
def pack_2(p1: uint256, p2: uint256) -> uint256:
    """
    @notice Packs 2 integers with values <= 2**128-1 into a uint256
    @param p1 The first integer to pack
    @param p2 The second integer to pack
    @return uint256 Integer with packed values
    """
    return p1 | (p2 << 128)


@pure
@internal
def unpack_2(packed: uint256) -> uint256[2]:
    """
    @notice Unpacks a uint256 into 2 integers
    @param packed The uint256 to unpack
    @return uint256[2] A list of length 2 with unpacked integers
    """
    return [packed & (2**128 - 1), packed >> 128]
