from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import MaxNLocator

ROOT = Path(__file__).resolve().parent.parent
SITE_LOG = ROOT / "tools" / "traffic" / "site_views.csv"  # GoatCounter
REPO_LOG = ROOT / "tools" / "traffic" / "views.csv"       # GitHub repository views
OUTPUT_IMAGE = ROOT / "tools" / "unified_dashboard_analytics.png"
WINDOW_DAYS = 14


def load_data(path: Path):
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
        date_col = [c for c in df.columns if "date" in c.lower()][0]
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.dropna(subset=[date_col]).sort_values(date_col)
        if df.empty:
            return None
        # The log files keep long-term history for the summary CSV; the chart
        # stays a readable sliding window.
        df = df.tail(WINDOW_DAYS)
        return df, date_col
    except Exception as exc:
        print(f"Warning: could not read {path}: {exc}")
        return None


def set_date_ticks(ax, df, date_col):
    ticks = df[date_col].tolist()
    if len(ticks) > 16:
        ticks = ticks[::2]
        if ticks[-1] != df[date_col].iloc[-1]:
            ticks.append(df[date_col].iloc[-1])
    ax.set_xticks(ticks)
    ax.set_xticklabels(
        [d.strftime("%Y-%m-%d") for d in ticks], rotation=45, ha="right", fontsize=7
    )
    ax.set_xlim(
        df[date_col].min() - pd.Timedelta(hours=12),
        df[date_col].max() + pd.Timedelta(hours=12),
    )


def generate_dashboard():
    fig, (ax_site, ax_repo) = plt.subplots(1, 2, figsize=(16, 6))

    # Website visits measured by GoatCounter
    site = load_data(SITE_LOG)
    if site:
        df, date_col = site
        ax_site.bar(
            df[date_col], df["visits"], color="tab:blue", alpha=0.65, width=0.8,
            label="Visits",
        )
        ax_site.set_title(
            f"Website Visits (GoatCounter) · to {df[date_col].iloc[-1]:%d %b %Y}"
        )
        ax_site.set_ylabel("Visits per day")
        ax_site.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax_site.set_xlabel("Date")
        set_date_ticks(ax_site, df, date_col)
        ax_site.legend(loc="upper left", frameon=False)
    else:
        ax_site.text(
            0.5, 0.5,
            "Website log missing or empty\n(tools/traffic/site_views.csv)",
            ha="center", va="center",
        )
        ax_site.set_axis_off()

    # GitHub repository traffic
    repo = load_data(REPO_LOG)
    if repo:
        df, date_col = repo
        view_col = "count" if "count" in df.columns else df.columns[1]
        unique_col = "uniques" if "uniques" in df.columns else df.columns[2]

        ax_repo.bar(
            df[date_col], df[view_col], color="tab:green", alpha=0.65, width=0.8,
            label="Total views",
        )
        ax_repo.set_ylabel("Total repository views", color="tab:green")
        ax_repo.tick_params(axis="y", labelcolor="tab:green")
        ax_repo.yaxis.set_major_locator(MaxNLocator(integer=True))

        ax_twin = ax_repo.twinx()
        ax_twin.plot(
            df[date_col], df[unique_col], color="tab:purple", linewidth=2,
            marker="s", label="Unique visitors",
        )
        ax_twin.set_ylabel("Unique visitors", color="tab:purple")
        ax_twin.tick_params(axis="y", labelcolor="tab:purple")
        ax_twin.yaxis.set_major_locator(MaxNLocator(integer=True))

        ax_repo.set_title(
            f"GitHub Repository Traffic – vogtpet/NHK · to {df[date_col].iloc[-1]:%d %b %Y}"
        )
        ax_repo.set_xlabel("Date")
        set_date_ticks(ax_repo, df, date_col)
        handles, labels = ax_repo.get_legend_handles_labels()
        twin_handles, twin_labels = ax_twin.get_legend_handles_labels()
        ax_repo.legend(
            handles + twin_handles, labels + twin_labels, loc="upper left", frameon=False
        )
    else:
        ax_repo.text(
            0.5, 0.5,
            "Repository log missing\n(tools/traffic/views.csv)",
            ha="center", va="center",
        )
        ax_repo.set_axis_off()

    fig.suptitle(
        "NHK Project – Website & Repository Traffic", fontsize=16, fontweight="bold"
    )
    fig.text(
        0.5,
        0.01,
        "GitHub repository traffic lags about two days behind GoatCounter; "
        "each panel ends at its latest available day.",
        ha="center",
        va="bottom",
        fontsize=8,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    plt.savefig(OUTPUT_IMAGE, dpi=100)
    plt.close(fig)
    print(f"Dashboard written to {OUTPUT_IMAGE}")


if __name__ == "__main__":
    generate_dashboard()
