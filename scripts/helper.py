import boa
from tests.utils.constants import (
    POOL_DEPLOYER,
    ERC20_DEPLOYER,
    FACTORY_DEPLOYER,
    GAUGE_DEPLOYER,
    VIEW_DEPLOYER,
    MATH_DEPLOYER,
)
from tests.utils.god_mode import GodModePool, god


def deploy_test_pool(initial_price=10**18, fee_on: bool = True, amp: int = 100) -> GodModePool:
    """Deploy a test pool with standard parameters"""
    deployer = god
    # boa.env.evm.patch.code_size_limit = 1000000  # Increase code size limit for deployment
    with boa.env.prank(deployer):
        # Deploy implementations
        pool_impl = POOL_DEPLOYER.deploy_as_blueprint()
        gauge_impl = GAUGE_DEPLOYER.deploy_as_blueprint()
        view_contract = VIEW_DEPLOYER.deploy()
        math_contract = MATH_DEPLOYER.deploy()

        # Deploy factory
        factory = FACTORY_DEPLOYER.deploy()
        factory.initialise_ownership(deployer, deployer)
        factory.set_pool_implementation(pool_impl, 0)
        factory.set_gauge_implementation(gauge_impl)
        factory.set_views_implementation(view_contract)
        factory.set_math_implementation(math_contract)

        # Deploy tokens
        tokens = [
            ERC20_DEPLOYER.deploy("USDC", "USDC", 18),  # 18 decimals
            ERC20_DEPLOYER.deploy("WETH", "WETH", 18),  # 18 decimals
        ]
        # Deploy pool
        pool_addr = factory.deploy_pool(
            "USDC/WETH",
            "USDCWETH",
            tokens,
            0,
            int(amp * 10_000),  # A TODO i removed 1 0
            int(0.145 * 10**18),  # gamma (0.145 * 1e18)
            0 if not fee_on else int(10**10 * 100 / 10_000),  # mid_fee (10bps)
            0 if not fee_on else int(10**10 * 100 / 10_000),  # out_fee (100bps)
            int(0.001 * 10**18),  # fee_gamma
            int(1e-12 * 10**18),  # allowed_extra_profit
            int(1e-7 * 10**18),  # adjustment_step
            90,  # ma_exp_time
            initial_price,  # initial_price (3000 USDC per WETH)
        )
    pool = POOL_DEPLOYER.at(pool_addr)
    pool.set_periphery(view_contract, math_contract, sender=deployer)

    return GodModePool(POOL_DEPLOYER.at(pool_addr))
