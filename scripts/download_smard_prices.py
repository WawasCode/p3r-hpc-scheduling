#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, datetime as dt, json, urllib.request
from pathlib import Path

def main() -> None:
    parser = argparse.ArgumentParser(description="Download hourly Germany/Luxembourg wholesale prices from SMARD.")
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--region", default="DE-LU")
    parser.add_argument("--module", type=int, default=4169)
    parser.add_argument("--max-weeks", type=int, default=12, help="Limit weeks for a compact repo sample; set 999 for full year")
    parser.add_argument("--output", default="data/prices/smard_de_lu_2024_hourly.csv")
    args = parser.parse_args()
    base = f"https://www.smard.de/app/chart_data/{args.module}/{args.region}"; headers={"User-Agent":"Bachelor thesis simulation data downloader"}
    index=json.loads(urllib.request.urlopen(urllib.request.Request(f"{base}/index_hour.json", headers=headers), timeout=30).read().decode())
    rows=[]; seen=set(); weeks=0
    year_start = dt.datetime(args.year, 1, 1, tzinfo=dt.timezone.utc)
    year_end = dt.datetime(args.year + 1, 1, 1, tzinfo=dt.timezone.utc)
    # Hourly files are partitioned by ISO week. Fetch one week before the year
    # as well, because the first UTC hours of a year often live in the previous
    # ISO-week file.
    for week_ts in index["timestamps"]:
        week_dt=dt.datetime.fromtimestamp(week_ts/1000, tz=dt.timezone.utc)
        if not (year_start - dt.timedelta(days=7) <= week_dt < year_end): continue
        data=json.loads(urllib.request.urlopen(urllib.request.Request(f"{base}/{args.module}_{args.region}_hour_{week_ts}.json", headers=headers), timeout=30).read().decode())
        weeks += 1
        for timestamp_ms, price in data.get("series", []):
            if price is None or timestamp_ms in seen: continue
            timestamp=dt.datetime.fromtimestamp(timestamp_ms/1000, tz=dt.timezone.utc)
            if timestamp.year == args.year:
                seen.add(timestamp_ms); rows.append((timestamp_ms, timestamp.isoformat().replace("+00:00","Z"), float(price)))
        if weeks >= args.max_weeks: break
    rows.sort(); out=Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        writer=csv.writer(f); writer.writerow(["timestamp_ms","timestamp_utc","price_eur_per_mwh"]); writer.writerows(rows)
    print(f"Wrote {out} ({len(rows)} hourly prices from {weeks} SMARD weeks)")
if __name__ == "__main__": main()
