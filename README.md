# XDN Evaluation Script

## 1. run.py -- Run Experiment

**Output files** (in `results_<experiment_id>/`):
- `k6_raw_<model>.csv` -- raw k6 metrics
- `k6_raw_<model>_simplified.csv` -- simplified request-level CSV
- `crashes_<model>_timing.csv` -- crash event log
- `reconfig_<model>_timing.csv` -- reconfiguration event log

### Replica failure experiment (Remote)

```bash
python3 run.py \
    --config ../conf/gigapaxos.xdn.3way.cloudlab.properties \
    --experiment-id exp_linearizable_1000rps_v2 \
    --consistency linearizable \
    --service todo_linearizable \
    --target-host 10.10.1.2 \
    --target-port 2300 \
    --target-rate 1000 \
    --prealloc-vus 1000 \
    --max-vus 5000 \
    --warmup-tasks 50 \
    --duration 180 \
    --req-timeout 5s \
    --crash-schedule '{"100": "AR0", "125": "AR2"}'
```

### Leader change experiment (Remote)

```bash
python3 run.py \
  --config ../conf/gigapaxos.xdn.3way.cloudlab.properties \
  --experiment-id exp_leader_change_exp_v2 \
  --consistency linearizable \
  --service todo_linearizable \
  --target-host 10.10.1.1 \
  --target-port 2300 \
  --target-rate 1000 \
  --prealloc-vus 1000 \
  --max-vus 7500 \
  --warmup-tasks 50 \
  --duration 180 \
  --req-timeout 10s \
  --crash-schedule '{"125": "AR1"}'
```

### Reconfiguration experiment (Remote)

`--csv-time-format unix_milli` is used to enable millisecond-precision timestamps (required for downtime analysis in `parser.py --detailed`).

```bash
python3 run.py \
    --config ../conf/gigapaxos.xdn.3way.cloudlab.properties \
    --experiment-id reconf_10_request_mixed_batchFalse_r6615_4 \
    --consistency linearizable \
    --service todo_linearizable \
    --target-host 10.10.1.2 \
    --target-port 2300 \
    --target-rate 10 \
    --prealloc-vus 15 \
    --max-vus 100 \
    --warmup-tasks 50 \
    --duration 120 \
    --req-timeout 5s \
    --reconfig-schedule '{"60": {"NODES": ["AR0", "AR1", "AR2"]}}' \
    --csv-time-format unix_milli
```

## 2. parser.py -- Parse Results

Reads `k6_raw_<model>_simplified.csv` and produces throughput and downtime CSVs.

### Throughput only (all experiment types)

```bash
python3 parser.py results_exp_linearizable_1000rps_v2 --model linearizable
```

Output: `parsed_data_linearizable.csv`

### With downtime analysis (reconfiguration experiments)

```bash
python3 parser.py results_reconf_10_request_mixed_batchFalse_r6615_2 \
    --model linearizable \
    --detailed \
    --bin-ms 200 \
    --padding-bins 1
```

Output: `parsed_data_linearizable.csv`, `downtime_summary.csv`, `parsed_data_linearizable_detailed.csv`

## 3. visualize_results.py -- Generate Plots

### Replica failure comparison (multi-folder)

```bash
python3 visualize_results.py \
    --mode default \
    --multi \
        linearizable:replica_failures/exp_linearizable_1000rps_v2 \
        sequential:replica_failures/exp_sequential_1000rps_v2 \
        eventual:replica_failures/exp_eventual_1000rps_v2 \
    --throughput-prefix parsed_data \
    --title "Throughput under replica failures" \
    --output replica_failures.png
```

### Leader change (single folder)

```bash
python3 visualize_results.py \
    --mode leader \
    --experiment exp_leader_change_exp_v2 \
    --models linearizable \
    --throughput-prefix parsed_data \
    --title "Leader Change" \
    --output leader_change.png
```

### Reconfiguration (two panels)

Requires `downtime_summary.csv` and a binned throughput CSV from `parser.py --detailed`.

```bash
python3 visualize_results.py \
    --mode reconfiguration \
    --zoom \
    --experiment results_reconf_10_request_mixed_batchFalse_r6615_2 \
    --models linearizable \
    --throughput-prefix parsed_data \
    --title "Reconfiguration throughput" \
    --output Reconfiguration throughput.png
```
