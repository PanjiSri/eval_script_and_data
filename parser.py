#!/usr/bin/env python3

import argparse
import csv
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List


SUMMARY_FILENAME = "downtime_summary.csv"


@dataclass(frozen=True)
class RequestRow:
    timestamp_ms: int
    status: int


@dataclass(frozen=True)
class DowntimeWindow:
    last_success_before_503: int
    first_503: int
    last_503: int
    first_success_after_503: int

    @property
    def total_downtime_ms(self) -> int:
        return self.first_success_after_503 - self.last_success_before_503


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parse k6 simplified CSV in an experiment folder and emit "
            "throughput and downtime-focused CSV summaries."
        )
    )
    parser.add_argument(
        "experiment_dir",
        help=(
            "Experiment folder containing k6_raw_<model>_simplified.csv. "
            "Example: results_debug_503_issue_3"
        ),
    )
    parser.add_argument(
        "--model",
        default="linearizable",
        help="Consistency model name. Reads k6_raw_<model>_simplified.csv. Default: linearizable.",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Also generate downtime_summary.csv and parsed_data_<model>_detailed.csv (for reconfiguration experiments).",
    )
    parser.add_argument(
        "--bin-ms",
        type=int,
        default=200,
        help="Throughput bin size in milliseconds for --detailed. Default: 200.",
    )
    parser.add_argument(
        "--padding-bins",
        type=int,
        default=1,
        help="Number of bins to include before and after the downtime window for --detailed.",
    )
    args = parser.parse_args()

    if args.bin_ms <= 0:
        parser.error("--bin-ms must be positive.")
    if args.padding_bins < 0:
        parser.error("--padding-bins must be zero or greater.")

    return args


def resolve_experiment_dir(raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_dir():
        return candidate.resolve()

    script_relative = Path(__file__).resolve().parent / raw_path
    if script_relative.is_dir():
        return script_relative.resolve()

    sys.exit(f"Error: Experiment directory not found: {raw_path}")


def load_request_rows(csv_path: Path) -> List[RequestRow]:
    rows: List[RequestRow] = []

    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("group") == "::setup":
                continue

            status_raw = (row.get("status") or "").strip()
            timestamp_raw = (row.get("timestamp") or "").strip()
            if not status_raw or not timestamp_raw:
                continue

            try:
                rows.append(RequestRow(timestamp_ms=int(timestamp_raw), status=int(status_raw)))
            except ValueError:
                continue

    if not rows:
        sys.exit(f"Error: No non-setup request rows found in {csv_path}")

    # Normalize timestamps to milliseconds.
    # Unix seconds are 10 digits (< 1e12), milliseconds are 13 digits (> 1e12).
    if rows[0].timestamp_ms < 1e12:
        rows = [RequestRow(timestamp_ms=r.timestamp_ms * 1000, status=r.status) for r in rows]

    rows.sort(key=lambda row: row.timestamp_ms)
    return rows


def write_throughput_csv(output_path: Path, rows: List[RequestRow]) -> None:
    base_ts = rows[0].timestamp_ms

    max_second = 0
    throughput = Counter()

    for row in rows:
        second = int((row.timestamp_ms - base_ts) / 1000.0)
        max_second = max(max_second, second)
        if 200 <= row.status < 300:
            throughput[second] += 1

    with output_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["second", "throughput_rps"])
        for second in range(max_second + 1):
            writer.writerow([second, throughput.get(second, 0)])

    total = len(rows)
    success = sum(1 for r in rows if 200 <= r.status < 300)
    print(f"Wrote {output_path} ({total} requests, {success} successful)")


def detect_downtime_window(rows: Iterable[RequestRow]) -> DowntimeWindow:
    rows = list(rows)
    first_503 = next((row.timestamp_ms for row in rows if row.status == 503), None)
    last_503 = next((row.timestamp_ms for row in reversed(rows) if row.status == 503), None)

    if first_503 is None or last_503 is None:
        sys.exit("Error: No 503 responses found in the input CSV.")

    last_success_before_503 = next(
        (row.timestamp_ms for row in reversed(rows) if 200 <= row.status < 300 and row.timestamp_ms < first_503),
        None,
    )
    first_success_after_503 = next(
        (row.timestamp_ms for row in rows if 200 <= row.status < 300 and row.timestamp_ms > last_503),
        None,
    )

    if last_success_before_503 is None:
        sys.exit("Error: Could not find a successful request before the first 503.")
    if first_success_after_503 is None:
        sys.exit("Error: Could not find a successful request after the last 503.")

    return DowntimeWindow(
        last_success_before_503=last_success_before_503,
        first_503=first_503,
        last_503=last_503,
        first_success_after_503=first_success_after_503,
    )


def write_summary_csv(output_path: Path, downtime: DowntimeWindow, scenario_start_ms: int) -> None:
    rows = [
        (
            "last_success_before_503",
            downtime.last_success_before_503,
            f"{(downtime.last_success_before_503 - scenario_start_ms) / 1000.0:.3f}",
        ),
        (
            "first_503",
            downtime.first_503,
            f"{(downtime.first_503 - scenario_start_ms) / 1000.0:.3f}",
        ),
        (
            "last_503",
            downtime.last_503,
            f"{(downtime.last_503 - scenario_start_ms) / 1000.0:.3f}",
        ),
        (
            "first_success_after_503",
            downtime.first_success_after_503,
            f"{(downtime.first_success_after_503 - scenario_start_ms) / 1000.0:.3f}",
        ),
        ("total_downtime_ms", downtime.total_downtime_ms, "N/A"),
    ]

    with output_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "TS", "time_from_start_s"])
        writer.writerows(rows)


def write_binned_throughput_csv(
        output_path: Path,
        rows: Iterable[RequestRow],
        downtime: DowntimeWindow,
        bin_ms: int,
        padding_bins: int,
) -> None:
    rows = list(rows)
    scenario_start_ms = rows[0].timestamp_ms
    successful_rows = [row for row in rows if 200 <= row.status < 300]

    first_503_bin = (downtime.first_503 - scenario_start_ms) // bin_ms
    recovery_bin = (downtime.first_success_after_503 - scenario_start_ms) // bin_ms
    start_bin = max(0, first_503_bin - padding_bins)
    end_bin = recovery_bin + padding_bins

    successes_per_bin = Counter(
        (row.timestamp_ms - scenario_start_ms) // bin_ms
        for row in successful_rows
        if start_bin <= (row.timestamp_ms - scenario_start_ms) // bin_ms <= end_bin
    )

    with output_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["second", "successfull_op"])

        for bin_index in range(start_bin, end_bin + 1):
            bin_start_seconds = (bin_index * bin_ms) / 1000.0
            successful_ops = successes_per_bin.get(bin_index, 0)
            writer.writerow([f"{bin_start_seconds:.3f}", successful_ops])


def main() -> None:
    args = parse_args()
    experiment_dir = resolve_experiment_dir(args.experiment_dir)
    input_path = experiment_dir / f"k6_raw_{args.model}_simplified.csv"
    if not input_path.exists():
        sys.exit(f"Error: Input file not found: {input_path}")

    rows = load_request_rows(input_path)

    # Always generate throughput per-second
    throughput_path = experiment_dir / f"parsed_data_{args.model}.csv"
    write_throughput_csv(throughput_path, rows)

    # Generate downtime analysis if --detailed
    if args.detailed:
        scenario_start_ms = rows[0].timestamp_ms
        downtime = detect_downtime_window(rows)

        summary_path = experiment_dir / SUMMARY_FILENAME
        detailed_path = experiment_dir / f"parsed_data_{args.model}_detailed.csv"

        write_summary_csv(summary_path, downtime, scenario_start_ms)
        write_binned_throughput_csv(
            detailed_path,
            rows,
            downtime,
            bin_ms=args.bin_ms,
            padding_bins=args.padding_bins,
        )

        print(f"Wrote {summary_path}")
        print(f"Wrote {detailed_path}")
        print(f"Total downtime: {downtime.total_downtime_ms} ms")


if __name__ == "__main__":
    main()
