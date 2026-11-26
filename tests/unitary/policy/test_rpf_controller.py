"""RPFController: the hysteresis rule on a mock pool, then the call path through
an owner proxy into the real pool's set_fee_parameters.

OWNER_PROXY copies set_permission and forward from Curve's UnifiedOwnerProxy
(edao-proxy, contracts/UnifiedOwnerProxy.vy). The deployed proxy itself is covered by
test_mainnet_fork at a pinned block, opt-in: RPF_CONTROLLER_FORK=1 with ETH_RPC_URL.
"""

import os

import boa
import pytest
from eth_abi import encode
from eth_utils import keccak

from tests.conftest import INITIAL_PRICES, _crypto_swap_with_deposit, _deploy_pool
from tests.utils.constants import POOL_DEPLOYER

CONTROLLER = boa.load_partial("contracts/policies/RPFController.vy")

WAD = 10**18
BP = 10**14  # one basis point, as a gap
FEE_PRECISION = 10**10
FULL_RPF = FEE_PRECISION
BASELINE_RPF = 43 * FEE_PRECISION // 100
HARVEST_GAP = 40 * BP
RESTORE_GAP = 20 * BP
MIN_CHANGE_PERIOD = 600
WEEK = 7 * 86_400


def config(
    baseline_rpf=BASELINE_RPF,
    harvest_gap=HARVEST_GAP,
    restore_gap=RESTORE_GAP,
    min_change_period=MIN_CHANGE_PERIOD,
):
    return (baseline_rpf, harvest_gap, restore_gap, min_change_period)


SET_FEE_PARAMETERS = keccak(text="set_fee_parameters(uint256,uint256)")[:4]

POOL_MOCK = """
# pragma version 0.4.3

admin: public(address)
virtual_price: public(uint256)
lp_xcp_profit: public(uint256)
reserved_profit_fraction: public(uint256)
admin_fee: public(uint256)

@external
def set_admin(admin: address):
    self.admin = admin

@external
def set_profit(virtual_price: uint256, lp_xcp_profit: uint256):
    self.virtual_price = virtual_price
    self.lp_xcp_profit = lp_xcp_profit

@external
def set_fee_parameters(reserved_profit_fraction: uint256, admin_fee: uint256):
    assert msg.sender == self.admin, "only owner"
    self.reserved_profit_fraction = reserved_profit_fraction
    self.admin_fee = admin_fee
"""

OWNER_PROXY = """
# pragma version 0.4.3

interface IFactory:
    def accept_transfer_ownership(): nonpayable

MAX_CALLDATA_SIZE: constant(uint256) = 1024
MAX_OUTSIZE: constant(uint256) = 1024

dao: public(address)
permissions: public(HashMap[address, HashMap[address, HashMap[bytes4, bool]]])

@deploy
def __init__(_dao: address):
    self.dao = _dao

@external
def set_permission(_controller: address, _pool: address, _selector: bytes4, _allowed: bool):
    assert msg.sender == self.dao, "Unauthorized"
    self.permissions[_controller][_pool][_selector] = _allowed

@external
def forward(_pool: address, _calldata: Bytes[MAX_CALLDATA_SIZE]) -> Bytes[MAX_OUTSIZE]:
    selector: bytes4 = convert(slice(_calldata, 0, 4), bytes4)
    assert self.permissions[msg.sender][_pool][selector], "Unauthorized"
    return raw_call(_pool, _calldata, max_outsize=MAX_OUTSIZE)

@external
def accept_transfer_ownership(_factory: address):
    extcall IFactory(_factory).accept_transfer_ownership()
"""


@pytest.fixture
def dao():
    return boa.env.generate_address()


@pytest.fixture
def yb_dao():
    return boa.env.generate_address()


@pytest.fixture
def proxy(dao):
    return boa.loads(OWNER_PROXY, dao)


@pytest.fixture
def mock_pool(proxy):
    pool = boa.loads(POOL_MOCK)
    pool.set_admin(proxy.address)
    pool.set_fee_parameters(BASELINE_RPF, 0, sender=proxy.address)
    return pool


def deploy_controller(pool, proxy, dao, yb_dao, **kwargs):
    with boa.env.prank(yb_dao):
        controller = CONTROLLER.deploy(pool.address, proxy.address, config(**kwargs))
    proxy.set_permission(controller.address, pool.address, SET_FEE_PARAMETERS, True, sender=dao)
    return controller


@pytest.fixture
def controller(mock_pool, proxy, dao, yb_dao):
    return deploy_controller(mock_pool, proxy, dao, yb_dao)


LP_XCP_PROFIT = 105 * WAD // 100  # the thresholds are whole virtual prices at it


def set_gap(pool, gap, wei=0):
    """virtual_price / lp_xcp_profit - 1 == gap, then virtual price moved by wei."""
    assert LP_XCP_PROFIT * gap % WAD == 0
    pool.set_profit(LP_XCP_PROFIT * (WAD + gap) // WAD + wei, LP_XCP_PROFIT)


def test_deployment(controller, mock_pool, proxy, yb_dao):
    assert controller.POOL() == mock_pool.address
    assert controller.PROXY() == proxy.address
    assert tuple(controller.config()) == config()
    assert controller.last_change() == 0
    assert controller.owner() == yb_dao


@pytest.mark.parametrize(
    "args, reason",
    [
        (lambda pool, proxy: (boa.eval("empty(address)"), proxy, config()), "pool=0"),
        (lambda pool, proxy: (pool, boa.eval("empty(address)"), config()), "proxy=0"),
        (lambda pool, proxy: (pool, proxy, config(baseline_rpf=FULL_RPF + 1)), "baseline rpf"),
    ],
)
def test_constructor_rejects(mock_pool, proxy, args, reason):
    with boa.reverts(reason):
        CONTROLLER.deploy(*args(mock_pool.address, proxy.address))


@pytest.mark.parametrize(
    "gap, wei, pool_rpf, expected",
    [
        # From HARVEST_GAP up: 100%, whatever the pool has
        (HARVEST_GAP, 0, BASELINE_RPF, FULL_RPF),
        (HARVEST_GAP, 0, FULL_RPF, FULL_RPF),
        (300 * BP, 0, 0, FULL_RPF),
        # From RESTORE_GAP down: baseline, whatever the pool has
        (RESTORE_GAP, 0, FULL_RPF, BASELINE_RPF),
        (RESTORE_GAP, 0, BASELINE_RPF, BASELINE_RPF),
        (0, 0, FULL_RPF, BASELINE_RPF),
        # One wei inside either threshold, and between: 100% only if already there
        (HARVEST_GAP, -1, BASELINE_RPF, BASELINE_RPF),
        (HARVEST_GAP, -1, FULL_RPF, FULL_RPF),
        (RESTORE_GAP, 1, BASELINE_RPF, BASELINE_RPF),
        (RESTORE_GAP, 1, FULL_RPF, FULL_RPF),
        (30 * BP, 0, BASELINE_RPF, BASELINE_RPF),
        (30 * BP, 0, FULL_RPF, FULL_RPF),
        (30 * BP, 0, 95 * FEE_PRECISION // 100, BASELINE_RPF),  # set by a vote: back to baseline
    ],
)
def test_target_rpf(controller, mock_pool, proxy, gap, wei, pool_rpf, expected):
    mock_pool.set_fee_parameters(pool_rpf, 0, sender=proxy.address)
    set_gap(mock_pool, gap, wei)

    assert controller.target_rpf() == expected
    if expected == pool_rpf:
        with boa.reverts("no change"):
            controller.update()
    else:
        controller.update()
    assert mock_pool.reserved_profit_fraction() == expected


def test_gap_is_relative_to_lp_xcp_profit(controller, mock_pool):
    # 41 bp of the starting virtual price is under 40 bp of an lp_xcp_profit of 1.05
    mock_pool.set_profit(LP_XCP_PROFIT + 41 * BP, LP_XCP_PROFIT)
    assert controller.target_rpf() == BASELINE_RPF
    mock_pool.set_profit(LP_XCP_PROFIT + 42 * BP, LP_XCP_PROFIT)
    assert controller.target_rpf() == FULL_RPF


def test_empty_pool_is_no_gap(controller, mock_pool, proxy):
    mock_pool.set_fee_parameters(FULL_RPF, 0, sender=proxy.address)
    mock_pool.set_profit(0, 0)
    assert controller.target_rpf() == BASELINE_RPF


def test_virtual_price_below_lp_xcp_profit_is_no_gap(controller, mock_pool, proxy):
    # An A ramp can leave virtual price under the LP floor
    mock_pool.set_fee_parameters(FULL_RPF, 0, sender=proxy.address)
    mock_pool.set_profit(104 * WAD // 100, 105 * WAD // 100)

    assert controller.target_rpf() == BASELINE_RPF
    controller.update()
    assert mock_pool.reserved_profit_fraction() == BASELINE_RPF


def test_update_is_permissionless_and_keeps_admin_fee(controller, mock_pool, proxy):
    admin_fee = 12 * FEE_PRECISION // 100
    mock_pool.set_fee_parameters(BASELINE_RPF, admin_fee, sender=proxy.address)
    set_gap(mock_pool, HARVEST_GAP)

    controller.update(sender=boa.env.generate_address())
    assert mock_pool.reserved_profit_fraction() == FULL_RPF
    assert mock_pool.admin_fee() == admin_fee

    # A later admin fee is the one passed back, not the first
    boa.env.time_travel(seconds=MIN_CHANGE_PERIOD)
    admin_fee = 7 * FEE_PRECISION // 100
    mock_pool.set_fee_parameters(FULL_RPF, admin_fee, sender=proxy.address)
    set_gap(mock_pool, RESTORE_GAP)
    controller.update(sender=boa.env.generate_address())
    assert mock_pool.reserved_profit_fraction() == BASELINE_RPF
    assert mock_pool.admin_fee() == admin_fee


def test_hysteresis_cycle(controller, mock_pool):
    def step(gap, expected, changes):
        boa.env.time_travel(seconds=MIN_CHANGE_PERIOD)
        set_gap(mock_pool, gap)
        if changes:
            controller.update()
        else:
            with boa.reverts("no change"):
                controller.update()
        assert mock_pool.reserved_profit_fraction() == expected

    step(10 * BP, BASELINE_RPF, False)  # refilling
    step(39 * BP, BASELINE_RPF, False)
    step(41 * BP, FULL_RPF, True)  # harvest
    step(39 * BP, FULL_RPF, False)  # rebalances spend the gap
    step(21 * BP, FULL_RPF, False)
    step(19 * BP, BASELINE_RPF, True)  # refill
    step(21 * BP, BASELINE_RPF, False)
    step(39 * BP, BASELINE_RPF, False)
    step(41 * BP, FULL_RPF, True)


def test_min_change_period(controller, mock_pool):
    set_gap(mock_pool, HARVEST_GAP)
    controller.update()
    changed_at = boa.env.evm.patch.timestamp
    assert controller.last_change() == changed_at

    # The gap collapses at once: the way back waits out the period
    set_gap(mock_pool, 0)
    assert controller.target_rpf() == BASELINE_RPF
    with boa.reverts("too soon"):
        controller.update()
    boa.env.time_travel(seconds=MIN_CHANGE_PERIOD - 1)
    with boa.reverts("too soon"):
        controller.update()
    assert mock_pool.reserved_profit_fraction() == FULL_RPF

    boa.env.time_travel(seconds=1)
    controller.update()
    assert mock_pool.reserved_profit_fraction() == BASELINE_RPF
    assert controller.last_change() == changed_at + MIN_CHANGE_PERIOD

    # A call that changes nothing does not restart the period
    boa.env.time_travel(seconds=MIN_CHANGE_PERIOD)
    with boa.reverts("no change"):
        controller.update()
    assert controller.last_change() == changed_at + MIN_CHANGE_PERIOD
    set_gap(mock_pool, HARVEST_GAP)
    controller.update()
    assert mock_pool.reserved_profit_fraction() == FULL_RPF


def test_update_needs_the_dao_permission(mock_pool, proxy, dao, yb_dao):
    controller = deploy_controller(mock_pool, proxy, dao, yb_dao)
    proxy.set_permission(
        controller.address, mock_pool.address, SET_FEE_PARAMETERS, False, sender=dao
    )
    set_gap(mock_pool, HARVEST_GAP)

    with boa.reverts("Unauthorized"):
        controller.update()
    assert mock_pool.reserved_profit_fraction() == BASELINE_RPF


def test_update_needs_the_proxy_to_be_pool_admin(controller, mock_pool):
    mock_pool.set_admin(boa.env.generate_address())
    set_gap(mock_pool, HARVEST_GAP)

    with boa.reverts("only owner"):
        controller.update()


@pytest.mark.parametrize(
    "kwargs, reason",
    [
        ({"baseline_rpf": FULL_RPF + 1}, "baseline rpf"),
        ({"harvest_gap": WAD + 1}, "harvest gap"),
        ({"restore_gap": HARVEST_GAP}, "restore gap"),
        ({"harvest_gap": 0, "restore_gap": 0}, "restore gap"),
        ({"min_change_period": WEEK + 1}, "min change period"),
    ],
)
def test_set_config_rejects(controller, yb_dao, kwargs, reason):
    with boa.reverts(reason):
        controller.set_config(config(**kwargs), sender=yb_dao)
    assert tuple(controller.config()) == config()


def test_set_config_accepts_the_bounds(controller, yb_dao):
    for new in (
        config(baseline_rpf=0, harvest_gap=1, restore_gap=0, min_change_period=0),
        config(baseline_rpf=FULL_RPF, harvest_gap=WAD, restore_gap=WAD - 1, min_change_period=WEEK),
    ):
        controller.set_config(new, sender=yb_dao)
        assert tuple(controller.config()) == new


def test_set_config_is_owner_only(controller):
    with boa.reverts("ownable: caller is not the owner"):
        controller.set_config(config(baseline_rpf=0))


def test_new_baseline(controller, mock_pool, proxy, yb_dao):
    new_baseline = 30 * FEE_PRECISION // 100

    # set_config only stores the value: the pool changes at the next update()
    set_gap(mock_pool, 30 * BP)
    controller.set_config(config(baseline_rpf=new_baseline), sender=yb_dao)
    assert mock_pool.reserved_profit_fraction() == BASELINE_RPF
    controller.update()
    assert mock_pool.reserved_profit_fraction() == new_baseline

    # In the 100% mode a new baseline waits for the gap to fall to restore_gap
    boa.env.time_travel(seconds=MIN_CHANGE_PERIOD)
    mock_pool.set_fee_parameters(FULL_RPF, 0, sender=proxy.address)
    controller.set_config(config(), sender=yb_dao)
    with boa.reverts("no change"):
        controller.update()
    set_gap(mock_pool, RESTORE_GAP)
    controller.update()
    assert mock_pool.reserved_profit_fraction() == BASELINE_RPF


def test_new_gaps(controller, mock_pool, yb_dao):
    # 30 bp is between the first thresholds, and at or beyond each of the new ones
    set_gap(mock_pool, 30 * BP)
    assert controller.target_rpf() == BASELINE_RPF

    controller.set_config(config(harvest_gap=30 * BP, restore_gap=10 * BP), sender=yb_dao)
    assert controller.target_rpf() == FULL_RPF
    controller.update()
    assert mock_pool.reserved_profit_fraction() == FULL_RPF

    boa.env.time_travel(seconds=MIN_CHANGE_PERIOD)
    controller.set_config(config(harvest_gap=60 * BP, restore_gap=30 * BP), sender=yb_dao)
    assert controller.target_rpf() == BASELINE_RPF
    controller.update()
    assert mock_pool.reserved_profit_fraction() == BASELINE_RPF


def test_new_min_change_period_counts_from_the_last_change(controller, mock_pool, yb_dao):
    set_gap(mock_pool, HARVEST_GAP)
    controller.update()
    set_gap(mock_pool, 0)

    # Longer: the change 600 seconds would have allowed now waits for an hour
    controller.set_config(config(min_change_period=3_600), sender=yb_dao)
    boa.env.time_travel(seconds=MIN_CHANGE_PERIOD)
    with boa.reverts("too soon"):
        controller.update()

    # Shorter: allowed at once
    controller.set_config(config(min_change_period=60), sender=yb_dao)
    controller.update()
    assert mock_pool.reserved_profit_fraction() == BASELINE_RPF

    # Zero: two changes in one block
    controller.set_config(config(min_change_period=0), sender=yb_dao)
    set_gap(mock_pool, HARVEST_GAP)
    controller.update()
    set_gap(mock_pool, 0)
    controller.update()
    assert mock_pool.reserved_profit_fraction() == BASELINE_RPF


def test_baseline_of_100_percent_never_changes_the_pool(mock_pool, proxy, dao, yb_dao):
    controller = deploy_controller(mock_pool, proxy, dao, yb_dao, baseline_rpf=FULL_RPF)
    mock_pool.set_fee_parameters(FULL_RPF, 0, sender=proxy.address)

    for gap in (0, RESTORE_GAP, 30 * BP, HARVEST_GAP):
        set_gap(mock_pool, gap)
        assert controller.target_rpf() == FULL_RPF


def test_ownership_transfer(controller, yb_dao):
    new_owner = boa.env.generate_address()
    controller.transfer_ownership(new_owner, sender=yb_dao)
    assert controller.owner() == new_owner
    with boa.reverts("ownable: caller is not the owner"):
        controller.set_config(config(baseline_rpf=0), sender=yb_dao)
    controller.set_config(config(baseline_rpf=0), sender=new_owner)


# ------------------------------- Real pool -------------------------------


def gap_of(pool):
    return pool.virtual_price() * WAD // pool.lp_xcp_profit() - WAD


def swap_there_and_back(pool, coins, user):
    """Sell a tenth of coin0's balance and sell the proceeds back: the pool ends
    where it started, plus two fees that raise virtual price."""
    dx = pool.balances(0) // 10
    boa.deal(coins[0], user, dx)
    with boa.env.prank(user):
        dy = pool.exchange(0, 1, dx, 0)
        pool.exchange(1, 0, dy, 0)
    boa.env.time_travel(seconds=600)


def test_real_pool_through_proxy(factory, owner, coins, params, deployer, user, dao, yb_dao):
    with boa.env.anchor():
        pool = POOL_DEPLOYER.at(_deploy_pool(factory, params, coins, deployer))
        _crypto_swap_with_deposit(coins, user, pool, INITIAL_PRICES)
        admin_fee = pool.admin_fee()
        assert admin_fee > 0  # so that passing it back is visible
        pool.set_fee_parameters(BASELINE_RPF, admin_fee, sender=owner)

        # The factory's admin, and so the pool's, becomes the proxy
        proxy = boa.loads(OWNER_PROXY, dao)
        factory.commit_transfer_ownership(proxy.address, sender=owner)
        proxy.accept_transfer_ownership(factory.address)
        assert pool.admin() == proxy.address
        controller = deploy_controller(pool, proxy, dao, yb_dao)

        # A fresh pool has no gap
        assert gap_of(pool) == 0
        assert controller.target_rpf() == BASELINE_RPF
        with boa.reverts("no change"):
            controller.update()

        # At baseline, fees open the gap
        for _ in range(200):
            if gap_of(pool) >= HARVEST_GAP:
                break
            swap_there_and_back(pool, coins, user)
        assert gap_of(pool) >= HARVEST_GAP
        assert controller.target_rpf() == FULL_RPF
        controller.update()
        assert pool.reserved_profit_fraction() == FULL_RPF
        assert pool.admin_fee() == admin_fee
        with boa.reverts("no change"):
            controller.update()

        # At 100% every bit of new profit is the LPs': the gap no longer grows
        gap, lp_xcp_profit = gap_of(pool), pool.lp_xcp_profit()
        for _ in range(5):
            swap_there_and_back(pool, coins, user)
        assert pool.lp_xcp_profit() > lp_xcp_profit
        assert gap_of(pool) <= gap


# ------------------------------ Mainnet fork -----------------------------

WETH_POOL = "0x656341Ef90b622c6634e0573772FfB7f3669b9f3"
FACTORY = "0x98EE851a00abeE0d95D08cF4CA2BdCE32aeaAF7F"
OLD_PROXY = "0xeDA0108D5bB8cdE2ba4A59E22F3Ed5d211C77187"  # the factory's admin at FORK_BLOCK
NEW_PROXY = "0xeDA010c47aeF0574fe98D02B0de3648f81Daf149"  # UnifiedOwnerProxy, with forward()
# 2026-11-26, the new proxy deployed and the handover not voted: RPF 43%, admin fee 0,
# a gap of 103.61 bp
FORK_BLOCK = 26499005


def call(target, signature, types, args, sender):
    data = keccak(text=signature)[:4] + encode(types, args)
    boa.env.raw_call(target, sender=sender, data=data)


def read(target, signature):
    return boa.env.raw_call(target, data=keccak(text=signature)[:4]).output


@pytest.mark.skipif(os.getenv("RPF_CONTROLLER_FORK") != "1", reason="opt-in RPC test")
def test_mainnet_fork():
    """The live WETH pool and the deployed UnifiedOwnerProxy, through the calls a DAO
    vote would make: hand the factory to the new proxy and permit the controller."""
    with boa.fork(os.environ["ETH_RPC_URL"], block_identifier=FORK_BLOCK, allow_dirty=True):
        pool = POOL_DEPLOYER.at(WETH_POOL)
        curve_dao = "0x" + read(NEW_PROXY, "dao()")[-20:].hex()
        assert pool.admin() == OLD_PROXY
        assert pool.reserved_profit_fraction() == BASELINE_RPF
        assert pool.admin_fee() == 0
        assert gap_of(pool) == 10360765036479140  # 103.61 bp

        controller = CONTROLLER.deploy(WETH_POOL, NEW_PROXY, config())
        assert controller.target_rpf() == FULL_RPF
        with boa.reverts():  # before the vote the proxy refuses the controller
            controller.update()

        # The vote. The old proxy only has execute()
        commit = keccak(text="commit_transfer_ownership(address)")[:4] + encode(
            ["address"], [NEW_PROXY]
        )
        call(
            OLD_PROXY, "execute(address,bytes)", ["address", "bytes"], [FACTORY, commit], curve_dao
        )
        call(NEW_PROXY, "accept_transfer_ownership(address)", ["address"], [FACTORY], curve_dao)
        call(
            NEW_PROXY,
            "set_permission(address,address,bytes4,bool)",
            ["address", "address", "bytes4", "bool"],
            [controller.address, WETH_POOL, SET_FEE_PARAMETERS, True],
            curve_dao,
        )
        assert pool.admin() == NEW_PROXY

        controller.update(sender=boa.env.generate_address())
        assert pool.reserved_profit_fraction() == FULL_RPF
        assert pool.admin_fee() == 0
        assert controller.last_change() == boa.env.evm.patch.timestamp
