import logging
import boa

import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from tests.utils.constants import (
    POOL_DEPLOYER,
    ERC20_DEPLOYER,
    FACTORY_DEPLOYER,
    MATH_DEPLOYER,
    GAUGE_DEPLOYER,
    VIEW_DEPLOYER,
)

WAD = 10**18
logger = logging.getLogger(__name__)


class Pool:
    """
    Pool wrapper class - deploys a new pool instance at init with given parameters.
    """

    def __init__(self, params=None, initial_price=1 * WAD):
        logger.info("Deploying new pool using Pool class __init__ with params dict...")
        # Set defaults from crypto preset
        defaults = dict(
            A=400_000,
            gamma=145_000_000_000_000,
            mid_fee=26_000_000,
            out_fee=45_000_000,
            fee_gamma=230_000_000_000_000,
            allowed_extra_profit=2_000_000_000_000,
            adjustment_step=146_000_000_000_000,
            ma_exp_time=866,
        )
        if params is not None:
            defaults.update(params)
        p = defaults

        # Generate addresses
        deployer = boa.env.generate_address("deployer")
        owner = boa.env.generate_address("owner")
        fee_receiver = boa.env.generate_address("fee_receiver")
        logger.info(
            f"Generated addresses - Deployer: {deployer}, Owner: {owner}, Fee Receiver: {fee_receiver}"
        )

        # Deploy implementations
        with boa.env.prank(deployer):
            pool_implementation = POOL_DEPLOYER.deploy_as_blueprint()
            gauge_implementation = GAUGE_DEPLOYER.deploy_as_blueprint()
            view_contract = VIEW_DEPLOYER.deploy()
            math_contract = MATH_DEPLOYER.deploy()
            factory = FACTORY_DEPLOYER.deploy()
            token0 = ERC20_DEPLOYER.deploy("Coin 0", "C0", 18)
            token1 = ERC20_DEPLOYER.deploy("Coin 1", "C1", 18)

        # Initialize factory
        factory.initialise_ownership(fee_receiver, owner, sender=deployer)
        with boa.env.prank(owner):
            factory.set_pool_implementation(pool_implementation, 0)
            factory.set_gauge_implementation(gauge_implementation)
            factory.set_views_implementation(view_contract)
            factory.set_math_implementation(math_contract)

        # Deploy the pool
        with boa.env.prank(deployer):
            pool_address = factory.deploy_pool(
                "Simulated Pool",
                "SIM",
                [token0.address, token1.address],
                0,
                p["A"],
                p["gamma"],
                p["mid_fee"],
                p["out_fee"],
                p["fee_gamma"],
                p["allowed_extra_profit"],
                p["adjustment_step"],
                p["ma_exp_time"],
                initial_price * WAD,
            )
        logger.info(f"Pool deployed at address: {pool_address}")
        self.instance = POOL_DEPLOYER.at(pool_address)
        self.address = self.instance.address
        self.coins = [token0, token1]

    def balances(self, i):
        return self.instance.balances(i)

    def balanceOf(self, address):
        return self.instance.balanceOf(address)

    def get_dy(self, i, j, dx):
        return self.instance.get_dy(i, j, dx)

    def __getattr__(self, name):
        return getattr(self.instance, name)

    def snapshot(self):
        bal = [self.balances(0), self.balances(1)]
        price_scale = self.price_scale()
        values = [
            bal[0],
            bal[1] * price_scale // WAD,
        ]
        return dict(
            balances=bal,
            values=values,
            total_value=sum(values),
            D=self.D(),
            virtual_price=self.virtual_price(),
            price_scale=price_scale,
            xcp_profit=self.xcp_profit(),
            xcp_profit_a=self.xcp_profit_a(),
            xcpx=(self.xcp_profit() + self.xcp_profit_a()) // 2,
            xcp_half=WAD + (self.xcp_profit() - WAD) // 2,
        )

    def snapshot_normalized(self):
        snapshot = self.snapshot()
        snapshot["D"] = snapshot["D"] / WAD
        snapshot["balances"] = [b / WAD for b in snapshot["balances"]]
        snapshot["values"] = [v / WAD for v in snapshot["values"]]
        snapshot["total_value"] = snapshot["total_value"] / WAD
        snapshot["virtual_price"] = snapshot["virtual_price"] / WAD
        snapshot["price_scale"] = snapshot["price_scale"] / WAD
        snapshot["xcp_profit"] = snapshot["xcp_profit"] / WAD
        snapshot["xcp_profit_a"] = snapshot["xcp_profit_a"] / WAD
        snapshot["xcpx"] = snapshot["xcpx"] / WAD
        snapshot["xcp_half"] = snapshot["xcp_half"] / WAD
        return snapshot
