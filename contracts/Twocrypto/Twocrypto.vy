# pragma version 0.4.1
from contracts.helpers import constants as c

import params
initializes: params

import amm
from snekmate.tokens import erc20
initializes: amm[erc20 := erc20, params := params]


from interfaces import ITwocrypto
implements: ITwocrypto

from contracts.helpers import packing_utils as utils

version: public(constant(String[8])) = "v2.1.0"

@deploy
def __init__(
    _name: String[64],
    _symbol: String[32],
    _coins: address[c.N_COINS],
    _math: address,
    _salt: bytes32, # not used, left for compatibility with legacy factory
    packed_precisions: uint256,
    packed_gamma_A: uint256,
    packed_fee_params: uint256,
    packed_rebalancing_params: uint256,
    initial_price: uint256,
):
    """
    @custom:inheritdoc ITwocrypto
    """
    amm.__init__(
        _name,
        _symbol,
        _coins,
        _math,
        packed_precisions,
        initial_price
    )

    params.__init__(
        msg.sender,
        packed_gamma_A,
        packed_fee_params,
        packed_rebalancing_params
    )

@external
@nonreentrant
def add_liquidity(
    amounts: uint256[c.N_COINS],
    min_mint_amount: uint256,
    receiver: address = msg.sender
) -> uint256:
    """
    @custom:inheritdoc ITwocrypto
    """
    return amm._add_liquidity(
        amounts,
        min_mint_amount,
        receiver
    )


@external
@nonreentrant
def remove_liquidity(
    amount: uint256,
    min_amounts: uint256[c.N_COINS],
    receiver: address = msg.sender,
) -> uint256[c.N_COINS]:
    """
    @custom:inheritdoc ITwocrypto
    """
    return amm._remove_liquidity(
        amount,
        min_amounts,
        receiver
    )

@external
@nonreentrant
def remove_liquidity_fixed_out(
    token_amount: uint256,
    i: uint256,
    amount_i: uint256,
    min_amount_j: uint256,
    receiver: address = msg.sender
) -> uint256:
    """
    @custom:inheritdoc ITwocrypto
    """
    return amm._remove_liquidity_fixed_out(
        token_amount,
        i,
        amount_i,
        min_amount_j,
        receiver,
    )

@external
@nonreentrant
def remove_liquidity_one_coin(
    lp_token_amount: uint256,
    i: uint256,
    min_amount: uint256,
    receiver: address = msg.sender
) -> uint256:
    """
    @custom:inheritdoc ITwocrypto
    """
    return amm._remove_liquidity_one_coin(
        lp_token_amount,
        i,
        min_amount,
        receiver
    )

@view
@external
def calc_withdraw_fixed_out(lp_token_amount: uint256, i: uint256, amount_i: uint256) -> uint256:
    """
    @custom:inheritdoc ITwocrypto
    """
    return amm._calc_withdraw_fixed_out(
        params._A_gamma(),
        lp_token_amount,
        i,
        amount_i,
    )[0]


@view
@external
def calc_withdraw_one_coin(lp_token_amount: uint256, i: uint256) -> uint256:
    return amm._calc_withdraw_fixed_out(
        params._A_gamma(),
        lp_token_amount,
        1 - i, # Here we flip i because we want to constrain the other coin to be zero.
        0, # We set the amount of coin[1 - i] to be withdrawn to 0.
    )[0]

@external
@nonreentrant
def exchange(
    i: uint256,
    j: uint256,
    dx: uint256,
    min_dy: uint256,
    receiver: address = msg.sender
) -> uint256:
    """
    @custom:inheritdoc ITwocrypto
    """
    return amm._pull_exchange(i, j, dx, min_dy, receiver)

@external
@nonreentrant
def exchange_received(
    i: uint256,
    j: uint256,
    dx: uint256,
    min_dy: uint256,
    receiver: address = msg.sender
) -> uint256:
    """
    @custom:inheritdoc ITwocrypto
    """
    return amm._push_exchange(i, j, dx, min_dy, receiver)

@external
@view
def fee_receiver() -> address:
    """
    @custom:inheritdoc ITwocrypto
    """
    return params._fee_receiver()

@view
@external
def admin() -> address:
    """
    @custom:inheritdoc ITwocrypto
    """
    return params._admin()

@view
@external
def calc_token_amount(amounts: uint256[2], deposit: bool) -> uint256:
    """
    @custom:inheritdoc ITwocrypto
    """
    return amm._calc_token_amount(
        amounts,
        deposit
    )


# TODO unwrap this
exports: amm.__interface__
exports: params.__interface__
