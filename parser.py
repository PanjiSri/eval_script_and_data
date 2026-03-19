"""
Usage:
    python3 extract_latency.py --input raw_raft.csv --output latency_raft.csv
    python3 extract_latency.py --input raw_xdn.csv  --output latency_xdn.csv
"""

import argparse
import csv
import statistics


def main():
    parser = argparse.ArgumentParser(
        description="Extract request latencies from k6 raw CSV output."
    )
    parser.add_argument("--input", required=True, help="Path to k6 raw CSV file")
    parser.add_argument("--output", required=True, help="Path to output latency CSV")
    args = parser.parse_args()

    latencies = []
    skipped_setup = 0
    skipped_other = 0

    with open(args.input, newline="") as fin:
        reader = csv.DictReader(fin)
        for row in reader:
            # Only care about HTTP request duration
            if row["metric_name"] != "http_req_duration":
                skipped_other += 1
                continue

            # Skip warmup/setup phase requests
            if row.get("group", "") == "::setup":
                skipped_setup += 1
                continue

            latencies.append(float(row["metric_value"]))

    # Write output CSV
    with open(args.output, "w", newline="") as fout:
        writer = csv.writer(fout)
        writer.writerow(["latency_ms"])
        for lat in latencies:
            writer.writerow([lat])

    # Print summary
    print(f"Extracted {len(latencies)} latency samples -> {args.output}")
    if skipped_setup:
        print(f"  Skipped {skipped_setup} setup/warmup rows")

    if latencies:
        latencies.sort()
        n = len(latencies)
        p50 = latencies[int(n * 0.50)]
        p95 = latencies[int(n * 0.95)]
        p99 = latencies[int(n * 0.99)]
        print(f"\n  Summary:")
        print(f"    n      = {n}")
        print(f"    mean   = {statistics.mean(latencies):.2f} ms")
        print(f"    p50    = {p50:.2f} ms")
        print(f"    p95    = {p95:.2f} ms")
        print(f"    p99    = {p99:.2f} ms")
        print(f"    min    = {latencies[0]:.2f} ms")
        print(f"    max    = {latencies[-1]:.2f} ms")


if __name__ == "__main__":
    main()
