#!/usr/bin/env python3
"""Merge the 14-day traffic exports into a persistent daily history.

GitHub only exposes the last 14 days of repository traffic, and the dashboard
plots a 14-day window. This script appends every day it sees to
tools/traffic/history.csv, so monthly and yearly totals survive beyond that
window. It is idempotent: rerunning it merges the same days again.

Inputs:
  tools/traffic/views.csv       Date,count,uniques   (GitHub repository)
  tools/traffic/site_views.csv  Date,visits          (GoatCounter)

Output:
  tools/traffic/history.csv     Date,website_visits,repo_views,repo_unique_visitors
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRAFFIC = ROOT / "tools" / "traffic"
HISTORY = TRAFFIC / "history.csv"
FIELDS = ["Date", "website_visits", "repo_views", "repo_unique_visitors"]


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_history():
    history = {}
    for row in read_csv(HISTORY):
        day = row.get("Date", "").strip()
        if not day:
            continue
        history[day] = {
            key: int(row.get(key) or 0) for key in FIELDS[1:]
        }
    return history


def merge_repository(history):
    changed = 0
    for row in read_csv(TRAFFIC / "views.csv"):
        day = row.get("Date", "").strip()
        if not day:
            continue
        entry = history.setdefault(day, {key: 0 for key in FIELDS[1:]})
        entry["repo_views"] = int(row.get("count") or 0)
        entry["repo_unique_visitors"] = int(row.get("uniques") or 0)
        changed += 1
    return changed


def merge_website(history):
    changed = 0
    for row in read_csv(TRAFFIC / "site_views.csv"):
        day = row.get("Date", "").strip()
        if not day:
            continue
        entry = history.setdefault(day, {key: 0 for key in FIELDS[1:]})
        entry["website_visits"] = int(row.get("visits") or 0)
        changed += 1
    return changed


def write_history(history):
    TRAFFIC.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for day in sorted(history):
            writer.writerow({"Date": day, **history[day]})


def main():
    history = load_history()
    repo_days = merge_repository(history)
    site_days = merge_website(history)
    write_history(history)
    print(
        f"history: {len(history)} days "
        f"(merged {repo_days} repository and {site_days} website rows)"
    )


if __name__ == "__main__":
    main()
