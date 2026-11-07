import os
import matplotlib.pyplot as plt
import pandas as pd

# Data log source definitions
SITE_LOG = "traffic/site_traffic.csv"
REPO_LOG = "traffic/views.csv"  # Your repository views history tracker file
OUTPUT_IMAGE = "unified_dashboard_analytics.png"


def load_and_process_data(file_path):
    if not os.path.exists(file_path):
        return None
    try:
        df = pd.read_csv(file_path)
        # Handle variant column headings dynamically
        date_col = [c for c in df.columns if "date" in c.lower()][0]
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.sort_values(date_col)
        return df, date_col
    except Exception as e:
        print(f"Warning: Error reading {file_path}: {e}")
        return None


def generate_dashboard():
    # Load dataset arrays
    site_data = load_and_process_data(SITE_LOG)
    repo_data = load_and_process_data(REPO_LOG)

    # Initialize side-by-side plot layout frame
    fig, (ax_site, ax_repo) = plt.subplots(1, 2, figsize=(16, 6))

    # ----------------------------------------------------
    # LEFT PANEL: Website Access Statistics (vogtpet.github.io/NHK/)
    # ----------------------------------------------------
    if site_data is not None:
        df_site, site_date = site_data
        df_site["CumulativeViews"] = df_site["DailyViews"].cumsum()

        color = "tab:blue"
        ax_site.set_xlabel("Date")
        ax_site.set_ylabel("Daily Page Views", color=color)
        ax_site.bar(
            df_site[site_date],
            df_site["DailyViews"],
            color=color,
            alpha=0.6,
            label="Daily Views",
        )
        ax_site.tick_params(axis="y", labelcolor=color)

        ax_site_twin = ax_site.twinx()
        color = "tab:red"
        ax_site_twin.set_ylabel("Overall Cumulative Access", color=color)
        ax_site_twin.plot(
            df_site[site_date],
            df_site["CumulativeViews"],
            color=color,
            linewidth=2,
            marker="o",
            label="Cumulative",
        )
        ax_site_twin.tick_params(axis="y", labelcolor=color)
        ax_site.set_title("Website Access Stats (*.github.io/NHK/)")
    else:
        ax_site.text(
            0.5,
            0.5,
            f"Website Log Missing\n({SITE_LOG})",
            ha="center",
            va="center",
        )

    # ----------------------------------------------------
    # RIGHT PANEL: GitHub Repository Traffic (://github.com)
    # ----------------------------------------------------
    if repo_data is not None:
        df_repo, repo_date = repo_data
        # Match standard GitHub repository tracking fields ('count' and 'uniques')
        view_col = (
            "count"
            if "count" in df_repo.columns
            else ("Views" if "Views" in df_repo.columns else df_repo.columns[1])
        )
        unique_col = (
            "uniques"
            if "uniques" in df_repo.columns
            else (
                "Uniques"
                if "Uniques" in df_repo.columns
                else df_repo.columns[2]
            )
        )

        color = "tab:green"
        ax_repo.set_xlabel("Date")
        ax_repo.set_ylabel("Total Git Repository Views", color=color)
        ax_repo.bar(
            df_repo[repo_date],
            df_repo[view_col],
            color=color,
            alpha=0.6,
            label="Total Views",
        )
        ax_repo.tick_params(axis="y", labelcolor=color)

        ax_repo_twin = ax_repo.twinx()
        color = "tab:purple"
        ax_repo_twin.set_ylabel("Unique Visitors", color=color)
        ax_repo_twin.plot(
            df_repo[repo_date],
            df_repo[unique_col],
            color=color,
            linewidth=2,
            marker="s",
            label="Unique Visitors",
        )
        ax_repo_twin.tick_params(axis="y", labelcolor=color)
        ax_repo.set_title("Repository Code Views (://github.com)")
    else:
        ax_repo.text(
            0.5,
            0.5,
            f"Repository Log Missing\n({REPO_LOG})",
            ha="center",
            va="center",
        )

    plt.suptitle(
        "Unified Analytics Dashboard: NHK Project",
        fontsize=16,
        fontweight="bold",
    )
    fig.tight_layout()

    # Save and display canvas frame
    plt.savefig(OUTPUT_IMAGE)
    print(f"Dashboard successfully generated and saved to '{OUTPUT_IMAGE}'.")
    plt.show()


if __name__ == "__main__":
    generate_dashboard()
