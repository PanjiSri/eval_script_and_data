import argparse
import csv
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

@dataclass
class ActiveReplica:
    name: str
    host: str
    port: int
    http_port: int

@dataclass
class Reconfigurator:
    name: str
    host: str
    port: int
    http_port: int

@dataclass
class Config:
    experiment_id: str
    consistency_model: str
    service_name: str
    target_host: str
    target_port: int
    target_rate: int
    load_duration: int
    prealloc_vus: int
    max_vus: int
    warmup_tasks: int
    req_timeout: str
    active_replicas: Dict[str, ActiveReplica]
    crash_schedule: Dict[int, str]
    is_remote: bool
    reconfig_schedule: Dict[int, dict]
    reconfigurators: Dict[str, Reconfigurator]
    rc_http_url: str
    target_host_after_reconfig: str
    target_port_after_reconfig: int
    csv_time_format: str

# Example :
'''
python run.py \
    --config ../conf/gigapaxos.xdn.3way.cloudlab.properties \
    --experiment-id exp_sequential_500rps_v1 \
    --consistency sequential \
    --service todo_sequential \
    --target-host 10.10.1.1 \
    --target-port 2300 \
    --target-rate 500 \
    --duration 180 \
    --prealloc-vus 200 \
    --max-vus 500 \
    --warmup-tasks 50 \
    --req-timeout 2s \
    --crash-schedule '{"60": "AR0", "90": "AR1"}'
'''

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="XDN Throughput Benchmark Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--config"
    )
    parser.add_argument(
        "--experiment-id",
        default=f"exp_{int(time.time())}"
    )
    parser.add_argument(
        "--consistency",
        default="sequential",
        choices=["linearizable", "sequential", "eventual", "causal", "pram"]
    )
    parser.add_argument(
        "--service",
        default="todo_sequential"
    )
    parser.add_argument(
        "--target-host"
    )
    parser.add_argument(
        "--target-port",
        type=int,
        default=2300
    )
    parser.add_argument(
        "--target-rate",
        type=int,
        default=250
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=180
    )
    parser.add_argument(
        "--prealloc-vus",
        type=int,
        default=200
    )
    parser.add_argument(
        "--max-vus",
        type=int,
        default=500
    )
    parser.add_argument(
        "--warmup-tasks",
        type=int,
        default=50
    )
    parser.add_argument(
        "--req-timeout",
        default="2s"
    )
    parser.add_argument(
        "--crash-schedule",
        default="{}"
    )
    parser.add_argument(
        "--reconfig-schedule",
        default="{}",
        help='JSON: second -> placement body. E.g. \'{"75": {"NODES": ["AR0", "AR1"]}}\''
    )
    parser.add_argument(
        "--rc-host",
        default=None,
        help="Reconfigurator HTTP host. Overrides config file. Default: localhost"
    )
    parser.add_argument(
        "--rc-port",
        type=int,
        default=None,
        help="Reconfigurator HTTP port. Overrides config file. Default: 3300"
    )
    parser.add_argument(
        "--target-host-after-reconfig",
        default=None,
        help="Host to switch to after reconfiguration causes failures"
    )
    parser.add_argument(
        "--target-port-after-reconfig",
        type=int,
        default=None,
        help="Port to switch to after reconfiguration causes failures"
    )
    parser.add_argument(
        "--csv-time-format",
        default=None,
        help="Set K6_CSV_TIME_FORMAT (e.g., 'unix_milli'). Required for reconfiguration downtime analysis."
    )

    return parser.parse_args()


def parse_gigapaxos_config(config_path: str) -> Tuple[Dict[str, ActiveReplica], Dict[str, Reconfigurator]]:
    replicas = {}
    reconfigurators = {}
    active_pattern = re.compile(r'^active\.(\w+)=([^:]+):(\d+)$')
    rc_pattern = re.compile(r'^reconfigurator\.(\w+)=([^:]+):(\d+)$')

    with open(config_path, 'r') as f:
        for line in f:
            line = line.strip()
            match = active_pattern.match(line)
            if match:
                name, host, port = match.groups()
                port = int(port)
                replicas[name] = ActiveReplica(
                    name=name, host=host, port=port, http_port=port + 300
                )

            rc_match = rc_pattern.match(line)
            if rc_match:
                name, host, port = rc_match.groups()
                port = int(port)
                reconfigurators[name] = Reconfigurator(
                    name=name, host=host, port=port, http_port=port + 300
                )

    return replicas, reconfigurators


def build_config(args: argparse.Namespace) -> Config:
    active_replicas = {}
    reconfigurators = {}
    is_remote = False
    target_host = args.target_host or "localhost"

    if args.config:
        if not os.path.exists(args.config):
            sys.exit(f"Error: Config file not found: {args.config}")

        active_replicas, reconfigurators = parse_gigapaxos_config(args.config)
        is_remote = True

    try:
        crash_schedule_raw = json.loads(args.crash_schedule)
        crash_schedule = {int(k): v for k, v in crash_schedule_raw.items()}
    except json.JSONDecodeError as e:
        sys.exit(f"Error: Invalid crash schedule JSON: {e}")

    try:
        reconfig_schedule_raw = json.loads(args.reconfig_schedule)
        reconfig_schedule = {int(k): v for k, v in reconfig_schedule_raw.items()}
    except json.JSONDecodeError as e:
        sys.exit(f"Error: Invalid reconfig schedule JSON: {e}")

    rc_host = args.rc_host
    rc_port = args.rc_port
    if rc_host is None and reconfigurators:
        first_rc = next(iter(reconfigurators.values()))
        rc_host = first_rc.host
    if rc_port is None and reconfigurators:
        first_rc = next(iter(reconfigurators.values()))
        rc_port = first_rc.http_port
    rc_host = rc_host or "localhost"
    rc_port = rc_port or 3300
    rc_http_url = f"http://{rc_host}:{rc_port}"

    return Config(
        experiment_id=args.experiment_id,
        consistency_model=args.consistency,
        service_name=args.service,
        target_host=target_host,
        target_port=args.target_port,
        target_rate=args.target_rate,
        load_duration=args.duration,
        prealloc_vus=args.prealloc_vus,
        max_vus=args.max_vus,
        warmup_tasks=args.warmup_tasks,
        req_timeout=args.req_timeout,
        active_replicas=active_replicas,
        crash_schedule=crash_schedule,
        is_remote=is_remote,
        reconfig_schedule=reconfig_schedule,
        reconfigurators=reconfigurators,
        rc_http_url=rc_http_url,
        target_host_after_reconfig=args.target_host_after_reconfig,
        target_port_after_reconfig=args.target_port_after_reconfig,
        csv_time_format=args.csv_time_format
    )


def kill_local_node(port: int) -> bool:
    print(f"\n[{time.strftime('%H:%M:%S')}] CRASHING local node on port {port}")
    result = subprocess.run(
        ["fuser", "-k", f"{port}/tcp"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return result.returncode == 0


def kill_remote_node(ar: ActiveReplica) -> bool:
    print(f"\n[{time.strftime('%H:%M:%S')}] CRASHING remote node {ar.name} ({ar.host}:{ar.http_port})")
    result = subprocess.run(
        ["ssh", ar.host, f"sudo fuser -k {ar.http_port}/tcp"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return result.returncode == 0


def trigger_reconfiguration(rc_http_url: str, service_name: str, body: dict) -> Tuple[bool, str]:
    url = f"{rc_http_url}/api/v2/services/{service_name}/placement"
    data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        method="PUT",
        headers={"Content-Type": "application/json"}
    )

    print(f"\n[{time.strftime('%H:%M:%S')}] RECONFIGURATION: PUT {url}")
    print(f"[{time.strftime('%H:%M:%S')}]   Body: {json.dumps(body)}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_text = resp.read().decode("utf-8")
            print(f"[{time.strftime('%H:%M:%S')}]   Response ({resp.status}): {resp_text[:200]}")
            return True, resp_text
    except urllib.error.HTTPError as e:
        resp_text = e.read().decode("utf-8", errors="replace")
        print(f"[{time.strftime('%H:%M:%S')}]   HTTP Error {e.code}: {resp_text[:200]}")
        return False, resp_text
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}]   Error: {e}")
        return False, str(e)


def write_simplified_csv(raw_file: str, simplified_file: str):
    if not os.path.exists(raw_file):
        print(f"Missing {raw_file}")
        return

    reqs = []
    durations = []
    waitings = []

    with open(raw_file, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            metric = row["metric_name"]
            if metric == "http_reqs":
                reqs.append(row)
            elif metric == "http_req_duration":
                durations.append(row)
            elif metric == "http_req_waiting":
                waitings.append(row)

    with open(simplified_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "method", "status", "success", "duration_ms", "waiting_ms", "error_code", "error", "group"])
        for req, dur, wait in zip(reqs, durations, waitings):
            writer.writerow([
                req["timestamp"],
                req["method"],
                req["status"],
                req["expected_response"],
                dur["metric_value"],
                wait["metric_value"],
                req["error_code"],
                req["error"],
                req["group"],
            ])

    print(f"Simplified CSV saved to {simplified_file} ({len(reqs)} requests)")


def write_crash_log(crash_log: str, crash_events: List[Tuple[float, str]]):
    if not crash_events:
        return

    with open(crash_log, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["crash_time_s", "target"])
        for crash_time, target in crash_events:
            writer.writerow([round(crash_time, 2), target])

    print(f"Wrote crash times to {crash_log}")


def write_reconfig_log(reconfig_log: str, reconfig_events: List[Tuple[float, str, bool]]):
    if not reconfig_events:
        return

    with open(reconfig_log, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["reconfig_time_s", "description", "success"])
        for reconfig_time, desc, success in reconfig_events:
            writer.writerow([round(reconfig_time, 2), desc, success])

    print(f"Wrote reconfiguration times to {reconfig_log}")


def run_benchmark(config: Config):
    results_folder = f"results_{config.experiment_id}"
    os.makedirs(results_folder, exist_ok=True)

    output_file = os.path.join(results_folder, f"k6_raw_{config.consistency_model}.csv")
    simplified_output = os.path.join(results_folder, f"k6_raw_{config.consistency_model}_simplified.csv")
    crash_log = os.path.join(results_folder, f"crashes_{config.consistency_model}_timing.csv")
    reconfig_log = os.path.join(results_folder, f"reconfig_{config.consistency_model}_timing.csv")

    # Clean up all output files from previous runs to prevent stale data
    for old_file in [output_file, simplified_output, crash_log, reconfig_log]:
        if os.path.exists(old_file):
            os.remove(old_file)

    print(f"[{time.strftime('%H:%M:%S')}] ==========================================")
    print(f"[{time.strftime('%H:%M:%S')}] Experiment ID: {config.experiment_id}")
    print(f"[{time.strftime('%H:%M:%S')}] Consistency model: {config.consistency_model}")
    print(f"[{time.strftime('%H:%M:%S')}] Service name: {config.service_name}")
    print(f"[{time.strftime('%H:%M:%S')}] Target: {config.target_host}:{config.target_port}")
    print(f"[{time.strftime('%H:%M:%S')}] Target rate: {config.target_rate} req/s")
    print(f"[{time.strftime('%H:%M:%S')}] Duration: {config.load_duration}s")
    print(f"[{time.strftime('%H:%M:%S')}] Request timeout: {config.req_timeout}")
    print(f"[{time.strftime('%H:%M:%S')}] PreAlloc VUs: {config.prealloc_vus}")
    print(f"[{time.strftime('%H:%M:%S')}] Max VUs: {config.max_vus}")
    print(f"[{time.strftime('%H:%M:%S')}] Warmup tasks: {config.warmup_tasks}")
    print(f"[{time.strftime('%H:%M:%S')}] Mode: {'Remote (CloudLab)' if config.is_remote else 'Local'}")
    print(f"[{time.strftime('%H:%M:%S')}] Results folder: {results_folder}/")

    if config.active_replicas:
        print(f"[{time.strftime('%H:%M:%S')}] Active Replicas:")
        for name, ar in config.active_replicas.items():
            print(f"[{time.strftime('%H:%M:%S')}]   {name}: {ar.host}:{ar.http_port}")

    if config.crash_schedule:
        print(f"[{time.strftime('%H:%M:%S')}] Crash schedule: {config.crash_schedule}")
    else:
        print(f"[{time.strftime('%H:%M:%S')}] Crash schedule: None (no crashes)")

    if config.reconfig_schedule:
        print(f"[{time.strftime('%H:%M:%S')}] Reconfig schedule: {config.reconfig_schedule}")
        print(f"[{time.strftime('%H:%M:%S')}] Reconfigurator URL: {config.rc_http_url}")
        if config.target_host_after_reconfig or config.target_port_after_reconfig:
            after_host = config.target_host_after_reconfig or config.target_host
            after_port = config.target_port_after_reconfig or config.target_port
            print(f"[{time.strftime('%H:%M:%S')}] Target after reconfig: {after_host}:{after_port}")
    else:
        print(f"[{time.strftime('%H:%M:%S')}] Reconfig schedule: None (no reconfiguration)")

    print(f"[{time.strftime('%H:%M:%S')}] ==========================================")
    print(f"[{time.strftime('%H:%M:%S')}] warming up...")

    k6_env = os.environ.copy()
    if config.csv_time_format:
        k6_env["K6_CSV_TIME_FORMAT"] = config.csv_time_format
    k6_env["XDN_TARGET_HOST"] = config.target_host
    k6_env["XDN_TARGET_PORT"] = str(config.target_port)
    k6_env["XDN_SERVICE_NAME"] = config.service_name
    k6_env["XDN_TARGET_RATE"] = str(config.target_rate)
    k6_env["XDN_LOAD_DURATION"] = f"{config.load_duration}s"
    k6_env["XDN_REQ_TIMEOUT"] = config.req_timeout
    k6_env["XDN_PREALLOC_VUS"] = str(config.prealloc_vus)
    k6_env["XDN_MAX_VUS"] = str(config.max_vus)
    k6_env["XDN_WARMUP_TASKS"] = str(config.warmup_tasks)

    if config.target_host_after_reconfig:
        k6_env["XDN_TARGET_HOST_AFTER"] = config.target_host_after_reconfig
    if config.target_port_after_reconfig:
        k6_env["XDN_TARGET_PORT_AFTER"] = str(config.target_port_after_reconfig)

    script_dir = Path(__file__).parent
    k6_script = script_dir / "benchmark.js"

    try:
        k6_process = subprocess.Popen(
            ["k6", "run", "--out", f"csv={output_file}", str(k6_script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=k6_env
        )
    except FileNotFoundError:
        sys.exit("Error: k6 not found.")

    remaining_crashes = dict(config.crash_schedule)
    crash_events = []
    remaining_reconfigs = dict(config.reconfig_schedule)
    reconfig_events = []
    load_start_time = None
    warmup_failed = False
    warmup_marker = "__WARMUP_COMPLETE__"

    try:
        # Phase 1: Wait for warmup to complete
        for line in iter(k6_process.stdout.readline, ''):
            print(line, end='', flush=True)

            if warmup_marker in line:
                load_start_time = time.time()
                print(f"\n[{time.strftime('%H:%M:%S')}] Warmup complete. Load test starting.")
                if config.crash_schedule:
                    print(f"[{time.strftime('%H:%M:%S')}] Crash schedule active: {config.crash_schedule}")
                if config.reconfig_schedule:
                    print(f"[{time.strftime('%H:%M:%S')}] Reconfig schedule active: {config.reconfig_schedule}")
                break

            if k6_process.poll() is not None:
                print("K6 finished before warmup completed.")
                warmup_failed = True
                break

        if load_start_time is None and not warmup_failed:
            print("Error: Never received warmup complete marker")
            warmup_failed = True

        # Phase 2: Monitor load test and inject crashes
        if not warmup_failed:
            def print_output():
                for line in iter(k6_process.stdout.readline, ''):
                    print(line, end='', flush=True)

            output_thread = threading.Thread(target=print_output, daemon=True)
            output_thread.start()

            # Monitor and inject crashes
            while True:
                elapsed = time.time() - load_start_time

                # Check if load test should be done (with buffer)
                if elapsed >= config.load_duration + 5:
                    break

                if k6_process.poll() is not None:
                    break

                # Check for scheduled crashes
                for crash_time in list(remaining_crashes.keys()):
                    if elapsed >= crash_time:
                        target = remaining_crashes[crash_time]

                        if config.is_remote and target in config.active_replicas:
                            ar = config.active_replicas[target]
                            kill_remote_node(ar)
                            crash_events.append((elapsed, f"{target}:{ar.host}"))
                        else:
                            try:
                                port = int(target)
                            except ValueError:
                                print(f"Warning: Cannot crash {target} in local mode")
                                del remaining_crashes[crash_time]
                                continue

                            kill_local_node(port)
                            crash_events.append((elapsed, f"localhost:{port}"))

                        del remaining_crashes[crash_time]

                # Check for scheduled reconfigurations
                for reconfig_time in list(remaining_reconfigs.keys()):
                    if elapsed >= reconfig_time:
                        body = remaining_reconfigs[reconfig_time]
                        success, resp = trigger_reconfiguration(
                            config.rc_http_url, config.service_name, body
                        )
                        desc = json.dumps(body)
                        reconfig_events.append((elapsed, desc, success))
                        del remaining_reconfigs[reconfig_time]

                time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nStopping test (Ctrl+C)")

    finally:
        if k6_process.poll() is None:
            print(f"[{time.strftime('%H:%M:%S')}] Terminating k6 process...")
            k6_process.terminate()
            try:
                k6_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print(f"[{time.strftime('%H:%M:%S')}] Force killing k6 process...")
                k6_process.kill()
                k6_process.wait()
        else:
            k6_process.wait()

        write_simplified_csv(output_file, simplified_output)
        write_crash_log(crash_log, crash_events)
        write_reconfig_log(reconfig_log, reconfig_events)

        print(f"\n[{time.strftime('%H:%M:%S')}] ==========================================")
        print(f"[{time.strftime('%H:%M:%S')}] Test Complete.")
        print(f"[{time.strftime('%H:%M:%S')}] Results saved to: {results_folder}/")
        print(f"[{time.strftime('%H:%M:%S')}] Raw data: k6_raw_{config.consistency_model}.csv")
        print(f"[{time.strftime('%H:%M:%S')}] Simplified: k6_raw_{config.consistency_model}_simplified.csv")
        if crash_events:
            print(f"[{time.strftime('%H:%M:%S')}] Crash log: crashes_{config.consistency_model}_timing.csv")
        if reconfig_events:
            print(f"[{time.strftime('%H:%M:%S')}] Reconfig log: reconfig_{config.consistency_model}_timing.csv")
        print(f"[{time.strftime('%H:%M:%S')}] ==========================================")


def main():
    args = parse_args()
    config = build_config(args)
    run_benchmark(config)

if __name__ == "__main__":
    main()
