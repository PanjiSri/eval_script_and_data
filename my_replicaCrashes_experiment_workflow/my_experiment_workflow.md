**STOP and CLEAN everything from Remote Server**

```bash
SSH_KEY_PATH=~/.ssh/id_cloudlab \
GP_USERNAME=username \
  ./bin/gpServer.sh \
    -DgigapaxosConfig=conf/gigapaxos.xdn.3way.cloudlab.properties \
    forceclear all
for h in 10.10.1.1 10.10.1.2 10.10.1.3 10.10.1.4; do
    ssh -i ~/.ssh/id_cloudlab username@$h "sudo rm -rf /tmp/gigapaxos /tmp/xdn"
  done
```
	
**START XDN**

```bash
./bin/gpServer.sh -DgigapaxosConfig=conf/gigapaxos.xdn.3way.cloudlab.properties start all
```

**LAUNCH service**

LINEARIZABLE
```bash
xdn launch todo_linearizable_golang -f services/todo-go/xdn-service-linearizable-golang.yaml
```

SEQUENTIAL
```
xdn launch todo_sequential_golang -f services/todo-go/xdn-service-sequential-golang.yaml
```

EVENTUAL
```
xdn launch todo_eventual_golang -f services/todo-go/xdn-service-eventual-golang.yaml
```

**SANITY CHECK**

LINEARIZABLE
```bash
curl -H "XDN: todo_linearizable_golang" -H "Content-Type: application/json" -X POST -d '{"item":"Task 1"}' 10.10.1.1:2300/api/todo/tasks
```

SEQUENTIAL
```bash
curl -H "XDN: todo_sequential_golang" -H "Content-Type: application/json" -X POST -d '{"item":"Task 1"}' 10.10.1.1:2300/api/todo/tasks
```

EVENTUAL
```bash
curl -H "XDN: todo_eventual_golang" -H "Content-Type: application/json" -X POST -d '{"item":"Task 1"}' 10.10.1.1:2300/api/todo/tasks
```

**PROBE THE LEADER**

LINEARIZABLE
```bash
for host in 10.10.1.1 10.10.1.2 10.10.1.3; do
  echo "Host $host:"
  curl -s "http://$host:2300/api/v2/services/todo_linearizable_golang/replica/info" \
    -H "XDN: todo_linearizable_golang" \
    | grep -o '"role":"[^"]*"'
done
```

SEQUENTIAL
```bash
for host in 10.10.1.1 10.10.1.2 10.10.1.3; do
  echo "Host $host:"
  curl -s "http://$host:2300/api/v2/services/todo_sequential_golang/replica/info" \
    -H "XDN: todo_sequential_golang" \
    | grep -o '"role":"[^"]*"'
done
```

EVENTUAL
```bash
for host in 10.10.1.1 10.10.1.2 10.10.1.3; do
  echo "Host $host:"
  curl -s "http://$host:2300/api/v2/services/todo_eventual_golang/replica/info" \
    -H "XDN: todo_eventual_golang" \
    | grep -o '"role":"[^"]*"'
done
```

**BENCHMARKING COMMAND**

LINEARIZABLE
```python
python3 run.py \
	  --config ../conf/gigapaxos.xdn.3way.cloudlab.properties \
	  --experiment-id replicaCrash_1000_request_mixed_TodoGolang_remote_linearizable_1 \
	  --consistency linearizable \
	  --service todo_linearizable_golang \
	  --target-host 10.10.1.1 \
	  --target-port 2300 \
	  --target-rate 1000 \
	  --prealloc-vus 1200 \
	  --max-vus 5000 \
	  --warmup-tasks 50 \
	  --duration 180 \
	  --req-timeout 5s \
	  --crash-schedule '{"100": "AR1", "125": "AR2"}' \
	  --csv-time-format unix_milli
```

SEQUENTIAL
```python
python3 run.py \
  --config ../conf/gigapaxos.xdn.3way.cloudlab.properties \
  --experiment-id replicaCrash_1000_request_mixed_TodoGolang_sequential_fixed_1 \
  --consistency sequential \
  --service todo_sequential_golang \
  --target-host 10.10.1.3 \
  --target-port 2300 \
  --target-rate 1000 \
  --prealloc-vus 1200 \
  --max-vus 5000 \
  --warmup-tasks 50 \
  --duration 180 \
  --req-timeout 5s \
  --crash-schedule '{"100": "AR0", "125": "AR1"}' \
  --csv-time-format unix_milli
```

EVENTUAL
```python
python3 run.py \
  --config ../conf/gigapaxos.xdn.3way.cloudlab.properties \
  --experiment-id replicaCrash_1000_request_mixed_TodoGolang_eventual_fixed_1 \
  --consistency eventual \
  --service todo_eventual_golang \
  --target-host 10.10.1.1 \
  --target-port 2300 \
  --target-rate 1000 \
  --prealloc-vus 1000 \
  --max-vus 5000 \
  --warmup-tasks 50 \
  --duration 180 \
  --req-timeout 5s \
  --crash-schedule '{"100": "AR1", "125": "AR2"}' \
  --csv-time-format unix_milli
```

**RETRIEVE THE RESULT**

```bash
rsync -azP username@clnode262.clemson.cloudlab.us:~/xdn/throughput_test/results_replicaCrash_1000_request_mixed_TodoGolang_eventual_fixed_1/ ./throughput_test/results_replicaCrash_1000_request_mixed_TodoGolang_eventual_fixed_1/
```

**PARSING**

LINEARIZABLE
```python
python3 parser.py results_replicaCrash_1000_request_mixed_TodoGolang_remote_linearizable_1 --model linearizable
```

SEQUENTIAL
```python
python3 parser.py results_replicaCrash_1000_request_mixed_TodoGolang_sequential_fixed_1 --model sequential
```

EVENTUAL
```python
python3 parser.py results_replicaCrash_1000_request_mixed_TodoGolang_eventual_fixed_1 --model eventual
```

**VISUALIZATION**

LINEARIZABLE
```python
python3 visualize_results.py --experiment results_replicaCrash_1000_request_mixed_TodoGolang_remote_linearizable_1 --models linearizable --output results_replicaCrash_1000_request_mixed_TodoGolang_remote_linearizable_1.png
```

SEQUENTIAL
```python
python3 visualize_results.py --experiment results_replicaCrash_1000_request_mixed_TodoGolang_sequential_fixed_1 --models sequential --output results_replicaCrash_1000_request_mixed_TodoGolang_sequential_fixed_1.png
```

EVENTUAL
```python
python3 visualize_results.py --experiment results_replicaCrash_1000_request_mixed_TodoGolang_eventual_fixed_1 --models eventual --output results_replicaCrash_1000_request_mixed_TodoGolang_eventual_fixed_1.png
```

COMBINATION
```python
python3 visualize_results.py --multi linearizable:results_replicaCrash_1000_request_mixed_TodoGolang_remote_linearizable_1 sequential:results_replicaCrash_1000_request_mixed_TodoGolang_sequential_fixed_1 eventual:results_replicaCrash_1000_request_mixed_TodoGolang_eventual_fixed_1 --output results_replicaCrash_1000_request_mixed_TodoGolang_grouped_fixed_1.png
```