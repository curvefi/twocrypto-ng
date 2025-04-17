import pandas as pd
import matplotlib.pyplot as plt
import logging
import numpy as np  # Import numpy for potential calculations
import os

logger = logging.getLogger(__name__)


def parse_list_string(s):
    """Helper to parse string representations of lists in the CSV."""
    try:
        # Remove brackets and split by comma, convert to float
        return [float(x.strip()) for x in s.strip("[]").split(",")]
    except:  # noqa
        # Return None or default value if parsing fails
        return [np.nan, np.nan]  # Assuming N_COINS=2


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Load data from CSV
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    csv_filename = os.path.join(cur_dir, "pool_simulation_results.csv")
    try:
        df = pd.read_csv(csv_filename)
        logger.info(f"Successfully loaded {csv_filename}")
        # Optional: Print columns to verify names
        # logger.info(f"DataFrame columns: {df.columns.tolist()}")
    except FileNotFoundError:
        logger.error(f"Error: {csv_filename} not found. Run main.py first.")
        exit()
    except Exception as e:
        logger.error(f"Error loading CSV: {e}")
        exit()

    # --- Create Subplots ---
    # Create a figure with two subplots stacked vertically
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)  # Share the x-axis

    # --- Subplot 1: Actor Values ---
    ax1 = axes[0]
    ax1.set_ylabel("Actor Value (in coin0 terms)", color="tab:blue")
    # Use flattened column names corresponding to the 'remove_liquidity' step
    ax1.plot(
        df["iteration"],
        df["remove_liquidity_lp_user_total_value"],
        label="LP Value",
        color="tab:blue",
    )
    ax1.plot(
        df["iteration"],
        df["remove_liquidity_trader_total_value"],
        label="Trader Value",
        color="tab:cyan",
    )
    ax1.plot(
        df["iteration"],
        df["remove_liquidity_admin_total_value"],
        label="Admin Value",
        color="tab:green",
    )
    ax1.plot(
        df["iteration"],
        df["remove_liquidity_admin_total_value"]
        + df["remove_liquidity_trader_total_value"]
        + df["remove_liquidity_lp_user_total_value"],
        label="Total Value",
        color="tab:purple",
    )

    ax1.tick_params(axis="y", labelcolor="tab:blue")
    ax1.grid(True, axis="y", linestyle="--", alpha=0.7)
    ax1.legend(loc="upper left")
    ax1.set_title("Actor Values After Each Cycle")

    # --- Subplot 2: Pool Metrics ---
    ax2 = axes[1]
    ax2.set_xlabel("Iteration")  # Set x-label only on the bottom plot
    ax2.set_ylabel("Pool Metric Value", color="tab:red")
    # Use flattened column names corresponding to the 'remove_liquidity' step
    ax2.plot(
        df["iteration"],
        df["remove_liquidity_pool_virtual_price"] / 1e18,
        label="Virtual Price",
        linestyle="--",
        color="tab:red",
    )
    ax2.plot(
        df["iteration"],
        df["remove_liquidity_pool_xcp_profit"] / 1e18,
        label="XCP Profit",
        linestyle="--",
        color="tab:orange",
    )
    ax2.plot(
        df["iteration"],
        df["remove_liquidity_pool_xcp_profit_a"] / 1e18,
        label="XCP Profit A",
        linestyle=":",
        color="tab:purple",
    )

    ax2.tick_params(axis="y", labelcolor="tab:red")
    ax2.grid(True, axis="y", linestyle="--", alpha=0.7)
    ax2.legend(loc="upper left")
    ax2.set_title("Pool Metrics After Each Cycle")

    # Overall title and layout adjustment
    # fig.suptitle(
    #     "Simulation Results After Each Cycle", fontsize=16
    # )  # Uncommented to add overall title
    fig.tight_layout(rect=[0, 0.03, 1, 0.97])  # Adjust layout to prevent title overlap
    plt.show()
