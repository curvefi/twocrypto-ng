import random
import boa
import matplotlib.pyplot as plt
import pandas as pd
from typing import Dict, List, Any
import os
import sys

# Add project root to sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tests.utils.god_mode import GodModePool
from scripts.helper import deploy_test_pool

boa.env.evm.patch.code_size_limit = 1000000  # Increase code size limit for deployment


class PoolSimulator:
    def __init__(self, pool: GodModePool):
        self.pool = pool
        self.history: List[Dict[str, Any]] = []
        self.step_counter = 0

    def record_state(self, action: str, **kwargs):
        """Record current pool state after an action"""
        # Check if price_scale changed (indicating rebalancing)
        current_price_scale = self.pool.instance.price_scale()
        previous_price_scale = None
        rebalanced = False

        if self.history:
            previous_price_scale = self.history[-1]["price_scale"]
            rebalanced = current_price_scale != previous_price_scale

        # Get allowed_extra_profit for threshold calculation
        allowed_extra_profit = self.pool.instance.allowed_extra_profit()

        admin_fee_claimed = False
        current_xcp_profit_a = self.pool.instance.xcp_profit_a()
        if self.history:
            previous_xcp_profit_a = self.history[-1]["xcp_profit_a"]
            admin_fee_claimed = current_xcp_profit_a != previous_xcp_profit_a

        # Calculate xp (scaled balances)
        balances = [self.pool.instance.balances(0), self.pool.instance.balances(1)]
        # precisions = [10**18, 10**18]  # Both tokens have 18 decimals in our test
        precisions = [1, 1]  # balances is 1e18, so precisions is 1 (it ups to 1e18 in contract)
        xp0 = balances[0] * precisions[0]
        xp1 = balances[1] * precisions[1] * current_price_scale // 10**18

        state = {
            "step": self.step_counter,
            "action": action,
            "virtual_price": self.pool.instance.virtual_price(),
            "vp_boosted": self.pool.virtual_price_boosted(),
            "xcp_profit": self.pool.instance.xcp_profit(),
            "xcp_profit_a": self.pool.instance.xcp_profit_a(),
            "price_scale": current_price_scale,
            "price_oracle": self.pool.instance.price_oracle(),
            "total_supply": self.pool.instance.totalSupply(),
            "donation_shares": self.pool.instance.internal._donation_shares(),
            "D": self.pool.instance.D(),
            "coin0_balance": self.pool.instance.balances(0),
            "coin1_balance": self.pool.instance.balances(1),
            "last_prices": self.pool.instance.last_prices(),
            "last_prices_scaled": self.pool.instance.last_prices() * current_price_scale // 10**18,
            "balances_price_scaled": balances[0] * current_price_scale // 10**18,
            "xp0": xp0,
            "xp1": xp1,
            "timestamp": boa.env.evm.patch.timestamp,
            "rebalanced": rebalanced,
            "price_scale_change": (current_price_scale - previous_price_scale)
            / previous_price_scale
            if previous_price_scale
            else 0,
            "allowed_extra_profit": allowed_extra_profit,
            "admin_fee_claimed": admin_fee_claimed,
            **kwargs,
        }
        if self.step_counter != 0:
            self.history.append(state)
            if rebalanced:
                print(
                    f"🔄 Rebalancing detected at step {self.step_counter}: price_scale changed from {previous_price_scale / 1e18:.6f} to {current_price_scale / 1e18:.6f}"
                )
            if admin_fee_claimed:
                print(
                    f"💰 Admin fee claimed at step {self.step_counter}: xcp_profit_a changed from {previous_xcp_profit_a / 1e18:.6f} to {current_xcp_profit_a / 1e18:.6f}"
                )
        self.step_counter += 1

    def donate_balanced(self, amount: int, user_id: str = "user1"):
        """Add balanced liquidity and record state"""
        self.pool.donate_balanced(amount)
        self.record_state("donate_balanced", amount=amount, user=user_id)
        return

    def add_liquidity_balanced(self, amount: int, user_id: str = "user1"):
        """Add balanced liquidity and record state"""
        lp_received = self.pool.add_liquidity_balanced(amount)
        self.record_state(
            "add_liquidity_balanced", amount=amount, lp_received=lp_received, user=user_id
        )
        return lp_received

    def add_liquidity_imbalanced(self, amounts: List[int], user_id: str = "user1"):
        """Add imbalanced liquidity and record state"""
        lp_received = self.pool.add_liquidity(amounts)
        self.record_state(
            "add_liquidity_imbalanced", amounts=amounts, lp_received=lp_received, user=user_id
        )
        return lp_received

    def exchange(self, i: int, dx: int, user_id: str = "user1"):
        """Perform exchange and record state"""
        dy = self.pool.exchange(i, dx, update_ema=False)
        self.record_state("exchange", coin_in=i, coin_out=1 - i, dx=dx, dy=dy, user=user_id)
        return dy

    def remove_liquidity_balanced(self, lp_amount: int, user_id: str = "user1"):
        """Remove balanced liquidity and record state"""
        amounts = self.pool.instance.remove_liquidity(lp_amount, [0, 0])
        self.record_state(
            "remove_liquidity_balanced", lp_amount=lp_amount, amounts_received=amounts, user=user_id
        )
        return amounts

    def remove_liquidity_one_coin(self, lp_amount: int, i: int, user_id: str = "user1"):
        """Remove liquidity in one coin and record state"""
        amount_received = self.pool.instance.remove_liquidity_one_coin(lp_amount, i, 0)
        self.record_state(
            "remove_liquidity_one_coin",
            lp_amount=lp_amount,
            coin_index=i,
            amount_received=amount_received,
            user=user_id,
        )
        return amount_received

    def remove_liquidity_fixed_out(
        self, lp_token_amount: int, i: int, amount_i: int, user_id: str = "user1"
    ):
        """Remove liquidity with a fixed amount for one coin and record state"""
        try:
            amount_j_received = self.pool.remove_liquidity_fixed_out(
                lp_token_amount, i, amount_i, 0
            )
            self.record_state(
                "remove_liquidity_fixed_out",
                lp_token_amount=lp_token_amount,
                coin_index_fixed=i,
                amount_fixed_coin=amount_i,
                amount_other_coin_received=amount_j_received,
                user=user_id,
            )
            return amount_j_received
        except Exception as e:
            print(f"Error during remove_liquidity_fixed_out for user {user_id}: {e}")
            self.record_state(
                "remove_liquidity_fixed_out_failed",
                lp_token_amount=lp_token_amount,
                coin_index_fixed=i,
                amount_fixed_coin=amount_i,
                user=user_id,
                error=str(e),
            )
            return None

    def time_travel(self, seconds: int):
        """Move time forward and record state"""
        boa.env.time_travel(seconds=seconds)
        self.record_state("time_travel", seconds=seconds)

    def get_dataframe(self) -> pd.DataFrame:
        """Convert history to pandas DataFrame for analysis"""
        return pd.DataFrame(self.history)

    def plot_metrics(self, save_path: str = None):
        """Plot key metrics over time"""
        df = self.get_dataframe()

        def add_event_highlights_and_markers(
            axis,
            y_column,
            rebalance_points,
            admin_fee_points,
            add_liq_points,
            remove_liq_points,
            donate_points,
        ):
            """Helper function to add event highlights and markers to an axis"""
            # Highlight rebalancing events with light red background
            if len(rebalance_points) > 0:
                for _, point in rebalance_points.iterrows():
                    axis.axvspan(
                        point["step"] - 0.5, point["step"] + 0.5, color="lightcoral", alpha=0.3
                    )

            # Highlight admin fee claims with light green background
            if len(admin_fee_points) > 0:
                for _, point in admin_fee_points.iterrows():
                    axis.axvspan(
                        point["step"] - 0.5, point["step"] + 0.5, color="lightgreen", alpha=0.3
                    )

            # Add markers for liquidity operations
            if len(add_liq_points) > 0:
                axis.scatter(
                    add_liq_points["step"],
                    add_liq_points[y_column] / 1e18,
                    marker="^",
                    color="green",
                    s=50,
                    alpha=0.7,
                    label="Add Liquidity",
                )
            if len(remove_liq_points) > 0:
                axis.scatter(
                    remove_liq_points["step"],
                    remove_liq_points[y_column] / 1e18,
                    marker="v",
                    color="red",
                    s=50,
                    alpha=0.7,
                    label="Remove Liquidity",
                )
            if len(donate_points) > 0:
                axis.scatter(
                    donate_points["step"],
                    donate_points[y_column] / 1e18,
                    marker="o",
                    color="orange",
                    s=50,
                    alpha=0.7,
                    label="Donation",
                )

        fig, axes = plt.subplots(6, 1, figsize=(20, 30))  # Increased to 6 rows
        fig.suptitle("Curve Pool Simulation Metrics", fontsize=18)
        plt.subplots_adjust(top=2)  # Adjust spacing to prevent overlap

        # Get event points for markers
        add_liq_points = df[df["action"].str.contains("add_liquidity", na=False)]
        remove_liq_points = df[df["action"].str.contains("remove_liquidity", na=False)]
        donate_points = df[df["action"].str.contains("donate_balanced", na=False)]
        rebalance_points = df[df["rebalanced"]]
        admin_fee_points = df[df["admin_fee_claimed"]]

        # Combined Virtual Price, XCP Profit and Threshold
        axes[0].plot(
            df["step"], df["virtual_price"] / 1e18, "b-", linewidth=2, label="Virtual Price"
        )
        axes[0].plot(
            df["step"], df["vp_boosted"] / 1e18, "b--", linewidth=2, label="Virtual Price Boosted"
        )
        axes[0].plot(df["step"], df["xcp_profit"] / 1e18, "g-", linewidth=2, label="XCP Profit")
        axes[0].plot(
            df["step"], df["xcp_profit_a"] / 1e18, "g--", linewidth=2, label="XCP Profit A (Dashed)"
        )

        # Calculate threshold line: 1 + (xcp_profit - 1)/2 + allowed_extra_profit
        threshold_pre_rebalancing = (
            1 + (df["xcp_profit"] / 1e18 - 1) / 2 + df["allowed_extra_profit"] / 1e18
        )
        axes[0].plot(
            df["step"],
            threshold_pre_rebalancing,
            "orange",
            linewidth=2,
            linestyle=":",
            label="Threshold pre rebalancing (1+(xcp-1)/2+allowed_extra_p)",
        )

        # Calculate simplified threshold line without allowed_extra_profit
        threshold_post_rebalancing = 1 + (df["xcp_profit"] / 1e18 - 1) / 2
        axes[0].plot(
            df["step"],
            threshold_post_rebalancing,
            "red",
            linewidth=2,
            linestyle=":",
            label="Threshold post rebalancing (1+(xcp-1)/2)",
        )

        add_event_highlights_and_markers(
            axes[0],
            "virtual_price",
            rebalance_points,
            admin_fee_points,
            add_liq_points,
            remove_liq_points,
            donate_points,
        )

        # Add proxy artists for background highlights to legend
        import matplotlib.patches as mpatches

        rebalance_patch = mpatches.Patch(color="lightcoral", alpha=0.3, label="Rebalancing Events")
        admin_fee_patch = mpatches.Patch(color="lightgreen", alpha=0.3, label="Admin Fee Claims")

        # Get existing legend handles and labels
        handles, labels = axes[0].get_legend_handles_labels()
        # Add background patches to legend
        handles.extend([rebalance_patch, admin_fee_patch])
        labels.extend(["Rebalancing Events", "Admin Fee Claims"])
        axes[0].legend(handles, labels, fontsize=8)

        axes[0].set_title("Virtual Price vs XCP Profit vs Threshold", fontsize=14)
        axes[0].set_xlabel("Step", fontsize=12)
        axes[0].set_ylabel("Value", fontsize=12)
        axes[0].grid(True, alpha=0.3)
        axes[0].set_xticks(range(0, len(df["step"]), 5))  # Display step every 5

        # Price Scale vs Oracle with rebalancing indicators
        axes[1].plot(df["step"], df["price_scale"] / 1e18, "r-", label="Price Scale", linewidth=2)
        axes[1].plot(
            df["step"], df["price_oracle"] / 1e18, "orange", label="Price Oracle", linewidth=2
        )

        add_event_highlights_and_markers(
            axes[1],
            "price_scale",
            rebalance_points,
            admin_fee_points,
            add_liq_points,
            remove_liq_points,
            donate_points,
        )

        # Add background patches to legend for axes[1]
        handles, labels = axes[1].get_legend_handles_labels()
        handles.extend([rebalance_patch, admin_fee_patch])
        labels.extend(["Rebalancing Events", "Admin Fee Claims"])
        axes[1].legend(handles, labels, fontsize=8)

        axes[1].set_title("Price Scale vs Oracle", fontsize=14)
        axes[1].set_xlabel("Step", fontsize=12)
        axes[1].set_ylabel("Price", fontsize=12)
        axes[1].grid(True, alpha=0.3)
        axes[1].set_xticks(range(0, len(df["step"]), 5))  # Display step every 5

        # Pool Balances
        axes[2].plot(df["step"], df["coin0_balance"] / 1e18, "cyan", label="Coin 0", linewidth=2)
        axes[2].plot(df["step"], df["coin1_balance"] / 1e18, "magenta", label="Coin 1", linewidth=2)

        add_event_highlights_and_markers(
            axes[2],
            "coin0_balance",
            rebalance_points,
            admin_fee_points,
            add_liq_points,
            remove_liq_points,
            donate_points,
        )

        axes[2].legend(fontsize=8)
        axes[2].set_title("Pool Balances", fontsize=14)
        axes[2].set_xlabel("Step", fontsize=12)
        axes[2].set_ylabel("Balance", fontsize=12)
        axes[2].grid(True, alpha=0.3)
        axes[2].set_xticks(range(0, len(df["step"]), 5))  # Display step every 5

        # LP Supply
        axes[3].plot(
            df["step"], df["total_supply"] / 1e18, "purple", linewidth=2, label="LP Supply"
        )
        axes[3].plot(
            df["step"],
            df["donation_shares"] / 1e18,
            "orange",
            linewidth=2,
            linestyle="--",
            label="Donation Shares",
        )

        add_event_highlights_and_markers(
            axes[3],
            "total_supply",
            rebalance_points,
            admin_fee_points,
            add_liq_points,
            remove_liq_points,
            donate_points,
        )

        axes[3].legend(fontsize=8)
        axes[3].set_title("LP Supply Over Time", fontsize=14)
        axes[3].set_xlabel("Step", fontsize=12)
        axes[3].set_ylabel("LP Tokens", fontsize=12)
        axes[3].grid(True, alpha=0.3)
        axes[3].set_xticks(range(0, len(df["step"]), 5))  # Display step every 5

        # Plot D (Invariant)
        axes[4].plot(df["step"], df["D"] / 1e18, "blue", linewidth=2, label="D (Invariant)")

        add_event_highlights_and_markers(
            axes[4],
            "D",
            rebalance_points,
            admin_fee_points,
            add_liq_points,
            remove_liq_points,
            donate_points,
        )

        axes[4].legend(fontsize=8)
        axes[4].set_title("Invariant (D) Over Time", fontsize=14)
        axes[4].set_xlabel("Step", fontsize=12)
        axes[4].set_ylabel("Value", fontsize=12)
        axes[4].grid(True, alpha=0.3)
        axes[4].set_xticks(range(0, len(df["step"]), 5))  # Display step every 5

        # Plot XP Balances (Scaled Balances)
        axes[5].plot(
            df["step"], df["xp0"] / 1e18, "darkblue", linewidth=2, label="XP[0] (Scaled Coin 0)"
        )
        axes[5].plot(
            df["step"], df["xp1"] / 1e18, "darkred", linewidth=2, label="XP[1] (Scaled Coin 1)"
        )

        add_event_highlights_and_markers(
            axes[5],
            "xp0",
            rebalance_points,
            admin_fee_points,
            add_liq_points,
            remove_liq_points,
            donate_points,
        )

        axes[5].legend(fontsize=8)
        axes[5].set_title("XP Balances (Scaled Balances) Over Time", fontsize=14)
        axes[5].set_xlabel("Step", fontsize=12)
        axes[5].set_ylabel("Scaled Balance", fontsize=12)
        axes[5].grid(True, alpha=0.3)
        axes[5].set_xticks(range(0, len(df["step"]), 5))  # Display step every 5

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches="tight")
        plt.show()

        # Print summary
        print("\n=== Simulation Summary ===")
        print(f"Total steps: {len(df)}")
        print(f"Total rebalancing events: {len(df[df['rebalanced'] == True])}")
        print(f"Total admin fee claims: {len(df[df['admin_fee_claimed'] == True])}")
        print(f"Initial virtual price: {df['virtual_price'].iloc[0] / 1e18:.6f}")
        print(f"Final virtual price: {df['virtual_price'].iloc[-1] / 1e18:.6f}")
        print(
            f"Virtual price change: {(df['virtual_price'].iloc[-1] / df['virtual_price'].iloc[0] - 1) * 100:.4f}%"
        )
        print(f"Initial XCP profit: {df['xcp_profit'].iloc[0] / 1e18:.6f}")
        print(f"Final XCP profit: {df['xcp_profit'].iloc[-1] / 1e18:.6f}")
        print(
            f"XCP profit change: {(df['xcp_profit'].iloc[-1] / df['xcp_profit'].iloc[0] - 1) * 100:.4f}%"
        )

    def save_history_to_csv(self, file_path: str = "pool_simulation_data.csv"):
        """Save the history of actions to a CSV file"""
        df = self.get_dataframe()
        df.to_csv(file_path, index=False)
        print(f"Simulation history saved to {file_path}")


def run_simulation():
    """Run a comprehensive simulation scenario"""
    print("Starting Curve Pool Simulation...")

    # Deploy pool
    pool = deploy_test_pool()
    simulator = PoolSimulator(pool)

    # Record initial state
    simulator.record_state("initial")

    # Phase 1: Initial liquidity provision
    simulator.add_liquidity_balanced(10_000 * 10**18, "initial_lp")

    # Phase 2:
    for i in range(200):
        coin_idx = random.randint(0, 1)
        balances = [simulator.pool.balances(0), simulator.pool.balances(1)]
        xps = simulator.pool.internal._xp(balances, simulator.pool.price_scale())

        simulator.time_travel(3600)  # 5 min to 1 hour
        # print(simulator.pool.new_xcp() - simulator.pool.old_xcp())
        # simulate_withdrawals(simulator.pool)

        # ========== Remove Liquidity ==========

        remove_liq = random.randint(0, 20)
        if remove_liq == 0:
            lp_balance = pool.instance.balanceOf(boa.env.eoa)
            if lp_balance == 0:
                print("No LP tokens left for remove_liquidity_fixed_out. Skipping.")
                break

            coin_idx_fixed = random.randint(0, 1)
            rand = random.randint(1, 100)
            lp_to_remove = lp_balance // 2  # Remove max 10%
            lp_to_remove = rand * lp_to_remove // 100  # Random amount to remove
            fixed_amount_to_remove = (
                pool.instance.balances(coin_idx_fixed) // 30
            )  # Remove 5% of the coin balance
            fixed_amount_to_remove = rand * fixed_amount_to_remove // 100

            print(
                f"Attempting remove_liquidity_fixed_out: LP={lp_to_remove / 1e18}, coin_idx={coin_idx_fixed}, amount_fixed={fixed_amount_to_remove / 1e18}"
            )
            simulator.remove_liquidity_fixed_out(
                lp_to_remove, coin_idx_fixed, fixed_amount_to_remove, f"remover_{i}"
            )
            continue

        # ========== Add Liquidity ==========
        add_liq = random.randint(0, 5)
        if add_liq == 0:
            rate = random.randint(1, 30)
            simulator.add_liquidity_balanced(int(balances[0] * rate // 100), "more lp")
            continue

        # ========== Donate ==========
        add_liq = random.randint(0, 10)
        if i > 20 and add_liq == 0:
            donate_amount = random.randint(50_000, 100_000) * 10**18
            try:
                simulator.donate_balanced(donate_amount, f"donor_{i}")
            except Exception as e:
                print(f"Error during donate_balanced for user {i}: {e}")
                continue
            continue

        # ========== Exchange ==========
        proportion = 50
        if xps[0] * proportion < xps[1]:
            coin_idx = 0
        elif xps[1] * proportion < xps[0]:
            coin_idx = 1
        exchange_amount = random.randint(10_000, 500_000) * 10**18
        simulator.exchange(coin_idx, exchange_amount, f"whale_trader_{i}")
    return simulator


def main():
    # fix random seed
    random.seed(1)

    simulator = run_simulation()
    try:
        # df = simulator.get_dataframe()
        simulator.plot_metrics(save_path="pool_simulation_results.png")
        simulator.save_history_to_csv("pool_simulation_data.csv")  # Save history to CSV
        # Find largest virtual price changes

    except Exception as e:
        print(f"Simulation failed: {e}")
        raise


if __name__ == "__main__":
    main()
