#!/usr/bin/env python3
"""Write monthly and yearly traffic totals to tools/traffic_summary.csv.

Reads the persistent daily history written by update_traffic_history.py and
aggregates website visits and repository traffic by month, by year, and for
all recorded days. The output is a small, plain CSV that is easy to open in a
spreadsheet or to read from another script.

Note: repo_unique_visitors is the sum of the daily unique-visitor values. It is
not a deduplicated count of people across the period, because the GitHub
traffic API only reports uniques per day.
"""
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "tools" / "traffic" / "history.csv"
OUTPUT = ROOT / "tools" / "traffic_summary.csv"

FIELDS = [
    "granularity",
    "period",
    "website_visits",
    "repo_views",
    "repo_unique_visitors",
]
METRICS = FIELDS[2:]


def read_history():
    if not HISTORY.exists():
        raise SystemExit(f"missing {HISTORY}; run update_traffic_history.py first")
    with HISTORY.open(newline="", encoding="utf-8") as handle:
        rows = []
        for row in csv.DictReader(handle):
            day = (row.get("Date") or "").strip()
            if len(day) < 10:
                continue
            rows.append(
                {
                    "day": day,
                    "month": day[:7],
                    "year": day[:4],
                    **{key: int(row.get(key) or 0) for key in METRICS},
                }
            )
    if not rows:
        raise SystemExit(f"no rows in {HISTORY}")
    return rows


def aggregate(rows, key):
    totals = defaultdict(lambda: {metric: 0 for metric in METRICS})
    for row in rows:
        bucket = totals[row[key]]
        for metric in METRICS:
            bucket[metric] += row[metric]
    return totals


def write_summary(rows):
    months = aggregate(rows, "month")
    years = aggregate(rows, "year")
    overall = {metric: sum(row[metric] for row in rows) for metric in METRICS}

    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for period in sorted(months):
            writer.writerow({"granularity": "month", "period": period, **months[period]})
        for period in sorted(years):
            writer.writerow({"granularity": "year", "period": period, **years[period]})
        writer.writerow({"granularity": "all", "period": "all", **overall})

    print(f"summary written to {OUTPUT} ({len(months)} months, {len(years)} years)")
    for period in sorted(months):
        data = months[period]
        print(
            f"  {period}  website={data['website_visits']:>6}  "
            f"repo_views={data['repo_views']:>6}  "
            f"repo_uniques_sum={data['repo_unique_visitors']:>4}"
        )


if __name__ == "__main__":
    write_summary(read_history())
