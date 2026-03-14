import argparse
import csv
import os
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt


def parse_args():
    parser = argparse.ArgumentParser(
        description="Plot per-model throughput with crash markers (Figure 17a style)."
    )
    parser.add_argument(
        "--mode",
        choices=["default", "leader", "reconfiguration"],
        default="default",
        help="Plot mode: 'default' for comparison, 'leader' for leader change, 'reconfiguration' for downtime analysis."
    )
    parser.add_argument(
        "--experiment",
        help="Path to experiment folder (e.g., results_exp01). Use with --models.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=["linearizable", "sequential", "eventual"],
        help="Consistency models to plot. Expects <model>.csv, or <prefix>_<model>.csv with --throughput-prefix.",
    )
    parser.add_argument(
        "--multi",
        nargs="+",
        help="Multi-folder mode: specify model:folder pairs (e.g., eventual:results_eventual_1 sequential:results_sequential_5).",
    )
    parser.add_argument(
        "--throughput-prefix",
        default=None,
        help="Throughput CSV filename prefix. Default: parsed_data_<model>.csv. If set, looks for <prefix>_<model>.csv.",
    )
    parser.add_argument(
        "--crash-log",
        help="Crash log CSV path. Defaults to crashes_<first model>_timing.csv in the experiment folder if present.",
    )
    parser.add_argument(
        "--reconfig-log",
        help="Reconfiguration log CSV path. Defaults to reconfig_<first model>_timing.csv in the experiment folder.",
    )
    parser.add_argument(
        "--reconfig-window",
        nargs=2,
        type=float,
        metavar=("START", "END"),
        help="Explicit reconfiguration window [start, end] in seconds. Auto-detected if omitted.",
    )
    parser.add_argument(
        "--zoom",
        action="store_true",
        help="Two-panel plot for reconfiguration mode: full throughput + zoomed downtime window.",
    )
    parser.add_argument(
        "--downtime-throughput",
        default=None,
        help="Downtime throughput CSV filename (relative to experiment folder). Default: parsed_data_<model>_detailed.csv.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output image file path.",
    )
    parser.add_argument(
        "--title",
        default="Throughput under replica failures",
        help="Plot title.",
    )
    args = parser.parse_args()

    if not args.experiment and not args.multi:
        parser.error("Either --experiment or --multi is required.")

    return args


def load_throughput(path: str) -> List[Tuple[int, float]]:
    required = {"second", "throughput_rps"}
    throughput = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if not required.issubset(reader.fieldnames or []):
            pass
        
        f.seek(0)
        reader = csv.DictReader(f)
        for row in reader:
            try:
                second = int(float(row.get("second") or row.get(" second")))
                val = float(row.get("throughput_rps") or row.get(" throughput_rps"))
            except (ValueError, TypeError, KeyError):
                continue
            throughput.append((second, val))

    if not throughput:
        raise ValueError(f"No throughput rows parsed from {path}.")

    throughput.sort(key=lambda x: x[0])
    return throughput


def load_crashes(path: str) -> List[float]:
    if not path or not os.path.exists(path):
        return []

    crashes = []
    with open(path, newline="") as f:
        first_line = f.readline()
        f.seek(0)
        if "crash_time" in first_line or "crash_time_s" in first_line:
            reader = csv.DictReader(f)
            for row in reader:
                val = row.get("crash_time_s") or row.get("crash_time")
                try:
                    crashes.append(float(val))
                except (TypeError, ValueError):
                    continue
        else:
            for line in f:
                for part in line.strip().replace(",", " ").split():
                    try:
                        crashes.append(float(part))
                    except ValueError:
                        continue

    return crashes


def load_reconfig_events(path: str) -> List[float]:
    if not path or not os.path.exists(path):
        return []

    events = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            val = row.get("reconfig_time_s")
            try:
                events.append(float(val))
            except (TypeError, ValueError):
                continue
    return events


def detect_reconfig_window(
    data: List[Tuple[int, float]],
    trigger_time: float,
) -> Tuple[float, float]:
    if not data:
        return (trigger_time, trigger_time + 10)

    pre_trigger_vals = [v for t, v in data if t < trigger_time and v > 0]
    if not pre_trigger_vals:
        pre_trigger_vals = [v for _, v in data if v > 0]

    median_val = sorted(pre_trigger_vals)[len(pre_trigger_vals) // 2] if pre_trigger_vals else 1
    threshold = median_val * 0.5
    recovery_threshold = median_val * 0.9

    # Floor trigger time to match integer-second granularity of throughput data
    trigger_sec = int(trigger_time)

    trigger_idx = 0
    for i, (t, v) in enumerate(data):
        if t >= trigger_sec:
            trigger_idx = i
            break

    window_start = trigger_time
    for i in range(trigger_idx, -1, -1):
        t, v = data[i]
        if v < threshold:
            window_start = t
        else:
            break

    # Scan forward: find where throughput fully recovers (>= 90% of baseline)
    window_end = trigger_time
    found_dip = False
    for i in range(trigger_idx, len(data)):
        t, v = data[i]
        if v < threshold:
            found_dip = True
            window_end = t
        elif found_dip:
            window_end = t
            if v >= recovery_threshold:
                break

    if window_end <= window_start:
        window_end = window_start + 5

    return (window_start, window_end)


def plot_throughput(
    series: Dict[str, List[Tuple[int, float]]],
    crashes: List[float],
    title: str,
    output: str,
):
    plt.figure(figsize=(10, 5))

    colors = ["tab:blue", "tab:orange", "tab:green", "tab:red", "tab:purple"]
    for idx, (label, data) in enumerate(series.items()):
        seconds = [t for t, _ in data]
        values = [v for _, v in data]
        plt.plot(seconds, values, label=label.capitalize(), linewidth=2, color=colors[idx % len(colors)])

    plt.ylabel("Throughput (req/s)")
    plt.xlabel("Elapsed time (s)")
    plt.title(title)
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.legend()

    if crashes:
        ymax = max(v for data in series.values() for _, v in data)
        text_y = ymax * 0.9 if ymax else 1
        for t in crashes:
            plt.axvline(x=t, color="tab:red", linestyle="--", linewidth=1.2)
            plt.text(t + 0.5, text_y, "Replica failure", rotation=90, va="top", ha="left", color="tab:red")

    max_second = max(max(t for t, _ in data) for data in series.values())
    max_value = max(max(v for _, v in data) for data in series.values())
    plt.xlim(left=0, right=max_second + 2)
    plt.ylim(bottom=0, top=max_value * 1.1 if max_value else 1)

    plt.tight_layout()
    plt.savefig(output, dpi=300, bbox_inches="tight")
    print(f"Saved plot to {output}")


def plot_leader_change(
    series: Dict[str, List[Tuple[int, float]]],
    crashes: List[float],
    title: str,
    output: str,
):
    plt.figure(figsize=(10, 5))
    
    colors = ["#1f77b4"] 
    
    for idx, (label, data) in enumerate(series.items()):
        seconds = [t for t, _ in data]
        values = [v for _, v in data]
        plt.plot(seconds, values, label=label.capitalize(), linewidth=2, color=colors[idx % len(colors)])

    plt.ylabel("Throughput (req/s)")
    plt.xlabel("Time (s)")
    plt.title(title)
    plt.grid(True, linestyle=":", alpha=0.6)
    
    if len(series) > 1:
        plt.legend()

    if crashes:
        all_vals = [v for data in series.values() for _, v in data]
        ymax = max(all_vals) if all_vals else 1
        
        for t in crashes:
            plt.axvline(x=t, color="red", linestyle="--", linewidth=1.5)
            plt.text(t, ymax * 0.95, " Leader crashes", color="red", fontweight="bold", ha="left", va="top")

    if series:
        max_second = max(max(t for t, _ in data) for data in series.values())
        plt.xlim(left=0, right=max_second + 5)
        plt.ylim(bottom=0)

    plt.tight_layout()
    plt.savefig(output, dpi=300, bbox_inches="tight")
    print(f"Saved leader change plot to {output}")


def detect_dip_and_recovery(
    data: List[Tuple[int, float]],
    trigger_time: float,
) -> Tuple[float, float]:
    """Detect the start of throughput dip and start of recovery around a trigger event.

    Returns (dip_start_time, recovery_start_time).
    """
    pre_trigger_vals = [v for t, v in data if t < trigger_time and v > 0]
    if not pre_trigger_vals:
        pre_trigger_vals = [v for _, v in data if v > 0]
    median_val = sorted(pre_trigger_vals)[len(pre_trigger_vals) // 2] if pre_trigger_vals else 1
    threshold = median_val * 0.5

    # Find dip start: first point at or after trigger where throughput drops below threshold
    dip_start = trigger_time
    for t, v in data:
        if t >= trigger_time and v < threshold:
            dip_start = t
            break

    # Find recovery start: last second below threshold before throughput resumes
    last_below = None
    in_dip = False
    for t, v in data:
        if t >= dip_start and v < threshold:
            in_dip = True
            last_below = t
        if in_dip and v >= threshold and t > dip_start:
            break

    recovery_start = last_below if last_below is not None else dip_start + 5

    return (dip_start, recovery_start)


def plot_reconfiguration(
    series: Dict[str, List[Tuple[int, float]]],
    reconfig_window: Tuple[float, float],
    title: str,
    output: str,
    dip_recovery: Tuple[float, float] = None,
):
    plt.figure(figsize=(10, 5))

    colors = ["#1f77b4"]

    for idx, (label, data) in enumerate(series.items()):
        seconds = [t for t, _ in data]
        values = [v for _, v in data]
        plt.plot(seconds, values, label=label.capitalize(), linewidth=2,
                 color=colors[idx % len(colors)])

    plt.ylabel("Throughput (req/s)")
    plt.xlabel("Elapsed time (s)")
    plt.title(title)
    plt.grid(True, linestyle=":", alpha=0.6)

    if reconfig_window:
        start, end = reconfig_window
        plt.axvspan(start, end, alpha=0.3, color="#FFD700", label="Reconfiguration window")

    if series:
        max_value = max(max(v for _, v in data) for data in series.values())
    else:
        max_value = 1

    ax = plt.gca()
    if dip_recovery:
        dip_start, recovery_start = dip_recovery
        extra_ticks = [dip_start, recovery_start]
        extra_labels = [f"{dip_start:.0f}", f"{recovery_start:.0f}"]
        # Filter out default ticks that are too close to the custom ones
        min_gap = 5
        current_ticks = list(ax.get_xticks())
        filtered_ticks = []
        filtered_labels = []
        for t in current_ticks:
            if all(abs(t - et) >= min_gap for et in extra_ticks):
                filtered_ticks.append(t)
                filtered_labels.append(f"{t:.0f}")
        ax.set_xticks(filtered_ticks + extra_ticks)
        ax.set_xticklabels(filtered_labels + extra_labels)
        # Color the dip/recovery tick labels
        tick_labels = ax.get_xticklabels()
        tick_labels[-2].set_color("tab:red")
        tick_labels[-1].set_color("tab:green")

    plt.legend()

    if series:
        max_second = max(max(t for t, _ in data) for data in series.values())
        plt.xlim(left=0, right=max_second + 5)
        plt.ylim(bottom=0, top=max_value * 1.1 if max_value else 1)

    plt.tight_layout()
    plt.savefig(output, dpi=300, bbox_inches="tight")
    print(f"Saved reconfiguration plot to {output}")


def load_downtime_throughput(path: str) -> List[Tuple[float, float]]:
    throughput: List[Tuple[float, float]] = []
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                second = float(row["second"])
                value = float(row["successfull_op"])
            except (KeyError, TypeError, ValueError):
                continue
            throughput.append((second, value))

    if not throughput:
        raise ValueError(f"No downtime throughput rows parsed from {path}.")

    throughput.sort(key=lambda item: item[0])
    return throughput


def load_downtime_window(path: str) -> Tuple[float, float]:
    values: Dict[str, float] = {}
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            metric = row.get("metric")
            if not metric:
                continue

            raw_value = row.get("time_from_start_s")
            if raw_value in (None, "", "N/A"):
                continue

            try:
                values[metric] = float(raw_value)
            except ValueError:
                continue

    required = {"last_success_before_503", "first_success_after_503"}
    missing = required - values.keys()
    if missing:
        raise ValueError(f"Missing downtime summary fields in {path}: {sorted(missing)}")

    return values["last_success_before_503"], values["first_success_after_503"]


def infer_bin_width(data: List[Tuple[float, float]]) -> float:
    if len(data) < 2:
        return 0.2

    deltas = []
    for i in range(1, len(data)):
        delta = round(data[i][0] - data[i - 1][0], 6)
        if delta > 0:
            deltas.append(delta)

    return min(deltas) if deltas else 0.2


def plot_reconfiguration_zoom(
    full_data: List[Tuple[float, float]],
    downtime_data: List[Tuple[float, float]],
    downtime_window: Tuple[float, float],
    label: str,
    title: str,
    output: str,
) -> None:
    fig, (ax_top, ax_bottom) = plt.subplots(
        2,
        1,
        figsize=(11, 8),
        gridspec_kw={"height_ratios": [3, 2]},
        constrained_layout=True,
    )

    # Top panel: full throughput
    seconds = [t for t, _ in full_data]
    values = [v for _, v in full_data]
    ax_top.plot(seconds, values, label=label.capitalize(), linewidth=2, color="#1f77b4")
    ax_top.set_ylabel("Throughput (req/s)")
    ax_top.set_xlabel("Elapsed time (s)")
    ax_top.set_title(title)
    ax_top.grid(True, linestyle=":", alpha=0.6)
    ax_top.legend()
    max_second = max(seconds)
    max_value = max(values)
    ax_top.set_xlim(left=0, right=max_second + 5)
    ax_top.set_ylim(bottom=0, top=max_value * 1.1 if max_value else 1)

    # Bottom panel: zoomed downtime
    seconds_z = [t for t, _ in downtime_data]
    values_z = [v for _, v in downtime_data]
    start, end = downtime_window
    bin_width = infer_bin_width(downtime_data)
    ax_bottom.plot(seconds_z, values_z, linewidth=2, color="#1f77b4")
    ax_bottom.axvspan(start, end, alpha=0.3, color="#FFD700", label="Reconfiguration window")
    ax_bottom.axvline(start, color="tab:red", linestyle="--", linewidth=1.5, label="Last success before 503")
    ax_bottom.axvline(end, color="tab:green", linestyle="--", linewidth=1.5, label="First success after 503")
    ax_bottom.set_title("Downtime Window")
    ax_bottom.set_xlabel("Elapsed time (s)")
    ax_bottom.set_ylabel("Successful ops / 200 ms")
    ax_bottom.grid(True, linestyle=":", alpha=0.6)
    ax_bottom.legend()
    max_value_z = max(values_z)
    ax_bottom.set_xlim(left=min(seconds_z), right=max(seconds_z) + bin_width)
    ax_bottom.set_ylim(bottom=0, top=max_value_z * 1.15 if max_value_z else 1)

    fig.savefig(output, dpi=300, bbox_inches="tight")
    print(f"Saved plot to {output}")


def main():
    args = parse_args()

    series = {}
    first_folder = None
    first_model = None

    prefix = args.throughput_prefix

    def throughput_filename(model: str) -> str:
        if prefix:
            return f"{prefix}_{model}.csv"
        return f"parsed_data_{model}.csv"

    if args.multi:
        for item in args.multi:
            if ":" not in item:
                raise ValueError(f"Invalid --multi format '{item}'. Expected 'model:folder'.")
            model, folder = item.split(":", 1)
            path = os.path.join(folder, throughput_filename(model))
            if not os.path.exists(path):
                raise FileNotFoundError(f"Missing throughput file for model '{model}': {path}")
            series[model] = load_throughput(path)
            print(f"Loaded {model} throughput from {path}")
            if first_folder is None:
                first_folder = folder
                first_model = model
    else:
        base = args.experiment
        first_folder = base
        for model in args.models:
            path = os.path.join(base, throughput_filename(model))
            if not os.path.exists(path):
                raise FileNotFoundError(f"Missing throughput file for model '{model}': {path}")
            series[model] = load_throughput(path)
            print(f"Loaded {model} throughput from {path}")
            if first_model is None:
                first_model = model

    crash_path = args.crash_log
    if not crash_path and first_folder and first_model:
        crash_path = os.path.join(first_folder, f"crashes_{first_model}_timing.csv")
    crashes = load_crashes(crash_path)
    if crashes:
        print(f"Loaded crash times from {crash_path}: {crashes}")
    else:
        print("No crash times loaded; skipping crash markers.")

    reconfig_window = None
    if args.mode == "reconfiguration":
        if args.reconfig_window:
            reconfig_window = tuple(args.reconfig_window)
        else:
            reconfig_path = args.reconfig_log
            if not reconfig_path and first_folder and first_model:
                reconfig_path = os.path.join(first_folder, f"reconfig_{first_model}_timing.csv")
            reconfig_events = load_reconfig_events(reconfig_path)
            if reconfig_events:
                print(f"Loaded reconfig times from {reconfig_path}: {reconfig_events}")
                trigger_time = reconfig_events[0]
                first_data = next(iter(series.values()))
                reconfig_window = detect_reconfig_window(first_data, trigger_time)
                print(f"Auto-detected reconfiguration window: {reconfig_window[0]:.1f}s - {reconfig_window[1]:.1f}s")
            else:
                print("Warning: No reconfig events found. No window will be drawn.")

    dip_recovery = None
    if args.mode == "reconfiguration" and reconfig_window:
        trigger_time = reconfig_window[0]
        first_data = next(iter(series.values()))
        dip_recovery = detect_dip_and_recovery(first_data, trigger_time)
        print(f"Dip starts at {dip_recovery[0]:.1f}s, recovery starts at {dip_recovery[1]:.1f}s")

    if args.mode == "reconfiguration" and args.zoom:
        if not args.experiment:
            raise ValueError("--zoom requires --experiment (single folder mode).")
        first_model = first_model or args.models[0]
        dt_filename = args.downtime_throughput or f"parsed_data_{first_model}_detailed.csv"
        dt_path = os.path.join(args.experiment, dt_filename)
        ds_path = os.path.join(args.experiment, "downtime_summary.csv")
        for path in [dt_path, ds_path]:
            if not os.path.exists(path):
                raise FileNotFoundError(f"Missing required input file: {path}")
        downtime_data = load_downtime_throughput(dt_path)
        downtime_window_zoom = load_downtime_window(ds_path)
        full_data = next(iter(series.values()))
        print(f"Loaded downtime throughput from {dt_path}")
        print(f"Loaded downtime window from {ds_path}: {downtime_window_zoom[0]:.3f}s - {downtime_window_zoom[1]:.3f}s")
        plot_reconfiguration_zoom(full_data, downtime_data, downtime_window_zoom, first_model, args.title, args.output)
    elif args.mode == "reconfiguration":
        plot_reconfiguration(series, reconfig_window, args.title, args.output, dip_recovery)
    elif args.mode == "leader":
        plot_leader_change(series, crashes, args.title, args.output)
    else:
        plot_throughput(series, crashes, args.title, args.output)


if __name__ == "__main__":
    main()