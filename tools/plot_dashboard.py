import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import MaxNLocator

ROOT = Path(__file__).resolve().parent.parent
REPO_LOG = ROOT / "traffic" / "views.csv"
OUTPUT_IMAGE = ROOT / "tools" / "unified_dashboard_analytics.png"


def load_repo_data(file_path):
    if not os.path.exists(file_path):
        return None
    try:
        df = pd.read_csv(file_path)
        date_col = [c for c in df.columns if "date" in c.lower()][0]
        df[date_col] = pd.to_datetime(df[date_col])
        return df.sort_values(date_col), date_col
    except Exception as exc:
        print(f"Warning: could not read {file_path}: {exc}")
        return None


def generate_dashboard():
    fig, ax = plt.subplots(figsize=(16, 6))
    data = load_repo_data(REPO_LOG)

    if data is None:
        ax.text(
            0.5,
            0.5,
            f"Repository traffic log missing\n({REPO_LOG})",
            ha="center",
            va="center",
        )
        ax.set_axis_off()
    else:
        df, date_col = data
        view_col = "count" if "count" in df.columns else df.columns[1]
        unique_col = "uniques" if "uniques" in df.columns else df.columns[2]

        view_color = "tab:green"
        ax.bar(
            df[date_col],
            df[view_col],
            color=view_color,
            alpha=0.65,
            width=0.8,
            label="Total views",
        )
        ax.set_ylabel("Total repository views", color=view_color)
        ax.tick_params(axis="y", labelcolor=view_color)
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))

        ax_twin = ax.twinx()
        unique_color = "tab:purple"
        ax_twin.plot(
            df[date_col],
            df[unique_col],
            color=unique_color,
            linewidth=2,
            marker="s",
            label="Unique visitors",
        )
        ax_twin.set_ylabel("Unique visitors", color=unique_color)
        ax_twin.tick_params(axis="y", labelcolor=unique_color)
        ax_twin.yaxis.set_major_locator(MaxNLocator(integer=True))

        # Label every data point so the last day is never missing or shifted.
        ax.set_xticks(df[date_col])
        ax.set_xticklabels(
            df[date_col].dt.strftime("%Y-%m-%d"), rotation=45, ha="right", fontsize=8
        )
        ax.set_xlim(
            df[date_col].min() - pd.Timedelta(hours=12),
            df[date_col].max() + pd.Timedelta(hours=12),
        )
        ax.set_xlabel("Date")
        ax.set_title("GitHub Repository Traffic – vogtpet/NHK")

        handles, labels = ax.get_legend_handles_labels()
        twin_handles, twin_labels = ax_twin.get_legend_handles_labels()
        ax.legend(handles + twin_handles, labels + twin_labels, loc="upper left", frameon=False)

    fig.suptitle(
        "NHK Project – Repository Analytics", fontsize=16, fontweight="bold"
    )
    fig.tight_layout()
    plt.savefig(OUTPUT_IMAGE, dpi=100)
    plt.close(fig)
    print(f"Dashboard written to {OUTPUT_IMAGE}")


if __name__ == "__main__":
    generate_dashboard()
