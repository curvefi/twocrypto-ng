from tests.utils.constants import (
    ERC20_DEPLOYER,
    FACTORY_DEPLOYER,
    GAUGE_DEPLOYER,
    VIEW_DEPLOYER,
    MATH_DEPLOYER,
)
import boa
from tests.utils.god_mode import GodModePool, god


def deploy_test_pool(initial_price=10**18, fee_on: bool = True) -> GodModePool:
    """Deploy a test pool with standard parameters"""
    deployer = god
    boa.env.evm.patch.code_size_limit = 1000000  # Increase code size limit for deployment
    with boa.env.prank(deployer):
        # Deploy implementations
        POOL_DEPLOYER = boa.load_partial("contracts/other/Twocrypto_experiment.vy")
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
            ERC20_DEPLOYER.deploy("USDC", "USDC", 18),  # 6 decimals
            ERC20_DEPLOYER.deploy("WETH", "WETH", 18),  # 18 decimals
        ]
        # Deploy pool
        pool_addr = factory.deploy_pool(
            "USDC/WETH",
            "USDCWETH",
            tokens,
            0,
            4000 * 1000,  # A TODO i removed 1 0
            145000000000000000,  # gamma (0.145 * 1e18)
            0 if not fee_on else 1000000,  # mid_fee (0.1%)
            0 if not fee_on else 45000000,  # out_fee (4.5%)
            230000000000000000,  # fee_gamma
            2300000000000000,  # allowed_extra_profit
            4500000000000000,  # adjustment_step
            600,  # ma_exp_time
            initial_price,  # initial_price (3000 USDC per WETH)
        )

    return GodModePool(POOL_DEPLOYER.at(pool_addr))
