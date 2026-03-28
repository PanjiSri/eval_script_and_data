
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
```bash
xdn launch todo_linearizable_golang -f services/todo-go/xdn-service-linearizable-golang.yaml
```

**SANITY CHECK**

```bash
curl -H "XDN: todo_linearizable_golang" -H "Content-Type: application/json" -X POST -d '{"item":"Task 1"}' 10.10.1.1:2300/api/todo/tasks
```

**PROBE THE LEADER**

```bash
for host in 10.10.1.1 10.10.1.2 10.10.1.3; do
  echo "Host $host:"
  curl -s "http://$host:2300/api/v2/services/todo_linearizable_golang/replica/info" \
    -H "XDN: todo_linearizable_golang" \
    | grep -o '"role":"[^"]*"'
done
```

**BENCHMARKING COMMAND**

HIGH THROUGHPUT :
```python
python3 run.py \
  --config ../conf/gigapaxos.xdn.3way.cloudlab.properties \
  --experiment-id leaderchanges_1000_request_mixed_TodoGolang_remote_fixed_2 \
  --consistency linearizable \
  --service todo_linearizable_golang \
  --target-host 10.10.1.2 \
  --target-port 2300 \
  --target-rate 1000 \
  --prealloc-vus 1200 \
  --max-vus 5000 \
  --warmup-tasks 50 \
  --duration 180 \
  --req-timeout 5s \
  --crash-schedule '{"125": "AR0"}' \
  --csv-time-format unix_milli
```

LOW THROUGHPUT :
```python
python3 run.py \
  --config ../conf/gigapaxos.xdn.3way.cloudlab.properties \
  --experiment-id leaderchanges_5_request_mixed_TodoGolang_remote_fixed \
  --consistency linearizable \
  --service todo_linearizable_golang \
  --target-host 10.10.1.2 \
  --target-port 2300 \
  --target-rate 5 \
  --prealloc-vus 10 \
  --max-vus 50 \
  --warmup-tasks 50 \
  --duration 30 \
  --req-timeout 5s \
  --crash-schedule '{"15": "AR1"}' \
  --csv-time-format unix_milli
```

**RETRIEVE THE RESULT**
```bash
rsync -azP username@clnode262.clemson.cloudlab.us:~/xdn/throughput_test/results_leaderchanges_1000_request_mixed_TodoGolang_remote_fixed_2/ ./throughput_test/results_leaderchanges_1000_request_mixed_TodoGolang_remote_fixed_2/
```

**PARSING**
```python
python3 parser.py results_leaderchanges_1000_request_mixed_TodoGolang_remote_fixed_2 --model linearizable
```

**VISUALIZATION**
```python
python visualize_results.py \
  --mode leader \
  --experiment results_leaderchanges_1000_request_mixed_TodoGolang_remote_fixed_2 \
  --models linearizable \
  --output results_leaderchanges_1000_request_mixed_TodoGolang_remote_fixed_2.png \
  --title "Leader Changes Experiment"
```

**DEBUGGGGG**

**GET**
```bash
curl -X GET "10.10.1.1:2300/api/todo/tasks" -H "XDN: todo_linearizable_golang"  
curl -X GET "10.10.1.2:2300/api/todo/tasks" -H "XDN: todo_linearizable_golang"  
curl -X GET "10.10.1.3:2300/api/todo/tasks" -H "XDN: todo_linearizable_golang"  
```

**POST**
```bash
AR0 : 
curl -H "XDN: todo_linearizable_golang" -H "Content-Type: application/json" -X POST -d '{"item":"Task 1"}' 10.10.1.1:2300/api/todo/tasks

AR1 :
curl -H "XDN: todo_linearizable_golang" -H "Content-Type: application/json" -X POST -d '{"item":"Task 2"}' 10.10.1.2:2300/api/todo/tasks

AR2 :
curl -H "XDN: todo_linearizable_golang" -H "Content-Type: application/json" -X POST -d '{"item":"Task 3"}' 10.10.1.3:2300/api/todo/tasks
```

