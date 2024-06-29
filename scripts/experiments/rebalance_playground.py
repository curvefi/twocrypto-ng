import boa
import matplotlib.pyplot as plt
import pandas as pd
from utils.pool_presets import get_preset_by_name
from utils.tokens import mint_for_testing

# D profit rebalancing
from contracts.main import CurveTwocrypto as Twocrypto
from contracts.main import CurveTwocryptoFactory as Factory
from contracts.main import CurveTwocryptoMath as Math
from contracts.main import CurveTwocryptoViews as Views
from contracts.mocks import ERC20Mock as ERC20

# xcp profit rebalancing
from contracts.old.xcp_profit_rebalancing import CurveTwocrypto as TwocryptoXcp
from contracts.old.xcp_profit_rebalancing import (
    CurveTwocryptoFactory as FactoryXcp,
)
from contracts.old.xcp_profit_rebalancing import CurveTwocryptoMath as MathXcp
from contracts.old.xcp_profit_rebalancing import (
    CurveTwocryptoViews as ViewsXcp,
)

deployer = boa.env.generate_address()
owner = boa.env.generate_address()
fee_receiver = boa.env.generate_address()

# deploying contracts
with boa.env.prank(deployer):
    amm_implementation = Twocrypto.deploy_as_blueprint()
    amm_xcp_implementation = TwocryptoXcp.deploy_as_blueprint()

    math_contract = Math()
    math_xcp_contract = MathXcp()

    views_contract = Views()
    views_xcp_contract = ViewsXcp()

    factory = Factory()
    factory_xcp = FactoryXcp()
    factory.initialise_ownership(fee_receiver, owner)
    factory_xcp.initialise_ownership(fee_receiver, owner)

# linking contracts
with boa.env.prank(owner):
    factory.set_pool_implementation(amm_implementation, 0)
    factory_xcp.set_pool_implementation(amm_xcp_implementation, 0)
    factory.set_views_implementation(views_contract)
    factory_xcp.set_views_implementation(views_contract)
    factory.set_math_implementation(math_contract)
    factory_xcp.set_math_implementation(math_contract)

params = get_preset_by_name("crypto")

coins = []
with boa.env.prank(deployer):
    coins.append(ERC20("BTC", "BTC", 18))
    coins.append(ERC20("ETH", "ETH", 18))

with boa.env.prank(deployer):
    swap = factory.deploy_pool(
        "new_pool",  # _name: String[64]
        "BTC<>ETH",  # _symbol: String[32]
        [coin.address for coin in coins],  # _coins: address[N_COINS]
        0,  # implementation_id: uint256
        params["A"],  # A: uint256
        params["gamma"],  # gamma: uint256
        params["mid_fee"],  # mid_fee: uint256
        params["out_fee"],  # out_fee: uint256
        params["fee_gamma"],  # fee_gamma: uint256
        params["allowed_extra_profit"],  # allowed_extra_profit: uint256
        params["adjustment_step"],  # adjustment_step: uint256
        params["ma_exp_time"],  # ma_exp_time: uint256
        int(1e18),  # initial_price: uint256
    )

    pool = Twocrypto.at(swap)

    swap = factory_xcp.deploy_pool(
        "old_pool",  # _name: String[64]
        "BTC<>ETH",  # _symbol: String[32]
        [coin.address for coin in coins],  # _coins: address[N_COINS]
        0,  # implementation_id: uint256
        params["A"],  # A: uint256
        params["gamma"],  # gamma: uint256
        params["mid_fee"],  # mid_fee: uint256
        params["out_fee"],  # out_fee: uint256
        params["fee_gamma"],  # fee_gamma: uint256
        params["allowed_extra_profit"],  # allowed_extra_profit: uint256
        params["adjustment_step"],  # adjustment_step: uint256
        params["ma_exp_time"],  # ma_exp_time: uint256
        int(1e18),
    )

    pool_xcp = TwocryptoXcp.at(swap)

pools = [pool, pool_xcp]

# create an empty dataframe
df_pool = pd.DataFrame(columns=["time", "D", "D_rebalance"])
df_pool_xcp = pd.DataFrame(columns=["time", "D", "D_rebalance"])


def take_snapshot(func_name):
    global df_pool, df_pool_xcp, pools
    xcpx = (pool.xcp_profit() / 2e18 + pool.xcp_profit_a() / 2e18 + 1) / 2
    xcpx_xcp = (
        (pool_xcp.xcp_profit() / 2e18 + pool_xcp.xcp_profit_a() / 2e18 + 1)
        / 2,
    )

    data_pool = pd.DataFrame(
        {
            "time": boa.env.evm.patch.timestamp,
            "D": pool.D(),
            "D_rebalance": pool.D_rebalance(),
            "xcp": pool.xcp_profit() / 1e18,
            "xcpx": xcpx,
            "op": func_name,
        },
        index=[0],
    )
    data_pool_xcp = pd.DataFrame(
        {
            "time": boa.env.evm.patch.timestamp,
            "D": pool_xcp.D(),
            "D_rebalance": 0,
            "xcp": pool_xcp.xcp_profit() / 1e18,
            "xcpx": xcpx_xcp,
            "op": func_name,
        },
        index=[0],
    )
    # convert to df

    df_pool = pd.concat([df_pool, data_pool])
    df_pool_xcp = pd.concat([df_pool_xcp, data_pool_xcp])


def snapshot(function):
    def wrapped(*args, delay=60, **kwargs):
        boa.env.time_travel(seconds=delay)
        function(*args, **kwargs)
        take_snapshot(function.__name__)

    return wrapped


trader = boa.env.generate_address("trader")


@snapshot
def add_liq(amounts, sender=trader):
    amounts = [int(a) for a in amounts]

    for p in pools:
        for coin, amount in zip(coins, amounts):
            # infinite approval
            coin.approve(p, 2**256 - 1, sender=sender)
            # mint the amount of tokens for the depositor
            mint_for_testing(coin, sender, amount)

        p.add_liquidity(amounts, 0, sender=sender)


@snapshot
def exchange(amount, i, sender=trader):
    amount = int(amount)

    for p in pools:
        coins[i].approve(p, 2**256 - 1, sender=sender)
        mint_for_testing(coins[i], sender, amount)
        p.exchange(i, 1 - i, amount, 0, sender=sender)


@snapshot
def donate(amounts):
    amounts = [int(a) for a in amounts]

    donor = boa.env.generate_address()
    for coin, amount in zip(coins, amounts):
        # mint the amount of tokens for the donor
        mint_for_testing(coin, donor, amount)
        coin.transfer(pool, amount, sender=donor)
    pool.donate(amounts, sender=donor)


@snapshot
def rem_liq(percentage, sender=trader):
    amount = int(pool.balanceOf(sender) * percentage)

    for p in pools:
        p.remove_liquidity(amount, [0] * 2, sender=sender)


@snapshot
def rem_liq_one(percentage, i, sender=trader):
    amount = int(pool.balanceOf(sender) * percentage)

    for p in pools:
        p.remove_liquidity_one_coin(amount, i, 0, sender=sender)


def plot_cumulative(df):
    df["time"] = pd.to_datetime(df["time"], unit="s")

    D = df["D"].astype(float)
    D_rebalance = df["D_rebalance"].astype(float)
    xcpx = df["xcpx"].astype(float)
    xcp = df["xcp"].astype(float)

    # Stack the values
    stacked_D_rebalance = D + D_rebalance

    fig, ax1 = plt.subplots()

    # Plotting the stacked values
    ax1.fill_between(df["time"], D, label="D", alpha=0.6)
    ax1.fill_between(
        df["time"], D, stacked_D_rebalance, label="D_rebalance", alpha=0.6
    )
    ax1.set_xlabel("Time")
    ax1.set_ylabel("Cumulative Value", color="b")
    ax1.legend(loc="lower right")

    # Secondary y-axis
    ax2 = ax1.twinx()
    ax2.plot(df["time"], xcpx, label="xcpx", color="r")
    ax2.plot(df["time"], xcp, label="xcp", color="g")
    ax2.set_ylabel("xcpx and xcp Values", color="r")
    ax2.legend(loc="right")

    plt.title("Composition of D with profit overlay")

    plt.show()

    print(df[["time", "D", "D_rebalance"]])


if __name__ == "__main__":
    add_liq([1e20] * 2)
    add_liq([1e20] * 2)
    add_liq([1e20] * 2)
    add_liq([1e20] * 2)
    rem_liq_one(0.1, 0)
    # rem_liq(0.1)
    # for i in range(3):
    #     exchange(1e21, 0)
    #     exchange(1e18, 1)

    plot_cumulative(df_pool_xcp)
    plot_cumulative(df_pool)
