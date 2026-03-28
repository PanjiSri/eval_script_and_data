### 1. Open New Terminal and SSH into Driver Node

```bash
ssh username@clnode262.clemson.cloudlab.us
```
### 2. SSH Key Configuration

1. Add ssh key into driver machine
```bash
scp ~/.ssh/id_cloudlab username@clnode262.clemson.cloudlab.us:~/.ssh/
```

2. Config setup
```
nano ~/.ssh/config
```

```
Host 10.10.1.*
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    User username 
    IdentityFile ~/.ssh/id_cloudlab
```

### 3. RSYNC XDN into Driver Machine

```bash
rsync -azP --exclude-from=exclude.txt ./ username@clnode262.clemson.cloudlab.us:~/xdn/
```

DELETE
```bash
rsync -azP --delete --exclude-from=exclude.txt ./ username@clnode262.clemson.cloudlab.us:~/xdn/
```
### 4. Initialize XDN within All Replica and RC

**At the beginning of the experiment**
3 Replica
```bash
./bin/xdnd dist-init \
  -config=conf/gigapaxos.xdn.3way.cloudlab.properties \
  -ssh-key=~/.ssh/id_cloudlab \
  -username=username
```

6 Replica
```bash
./bin/xdnd dist-init \
  -config=conf/gigapaxos.xdn.cloudlab.6.reconfiguration.properties \
  -ssh-key=~/.ssh/id_cloudlab \
  -username=username
```

**When there is an update in the XDN code**
```bash
./bin/xdnd deploy \
  -config=conf/gigapaxos.xdn.3way.cloudlab.properties \
  -ssh-key=~/.ssh/id_cloudlab \
  -username=username
```
### 5. Pull Todo Docker Images

```bash
docker pull sriwisma/todo_linearizable_golang
```

#### 6. STOP and CLEAN everything from Remote Server

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

#### 7. Start all servers

```bash
./bin/gpServer.sh -DgigapaxosConfig=conf/gigapaxos.xdn.3way.cloudlab.properties start all 2>&1 | tee debug_log/reconf_1000_request_mixed_TodoGolang_remote_fixed_3.log
```

#### 8. Deploy Todo Service

```bash
export XDN_CONTROL_PLANE=10.10.1.4
```

TODO :
```bash
xdn launch todo_linearizable_golang -f services/todo-go/xdn-service-linearizable-golang.yaml
```

#### 9. Sanity Check

TODO :
POST Request
```bash
curl -H "XDN: todo_linearizable_golang" -H "Content-Type: application/json" -X POST -d '{"item":"Task 1"}' 10.10.1.1:2300/api/todo/tasks
```

Probe the Leader
```bash
for host in 10.10.1.1 10.10.1.2 10.10.1.3; do
  echo "Host $host:"
  curl -s "http://$host:2300/api/v2/services/todo_linearizable_golang/replica/info" \
    -H "XDN: todo_linearizable_golang" \
    | grep -o '"role":"[^"]*"'
done
```

#### 10. BENCHMARKING COMMAND

TODO :
3 Replica
```python
python run.py \
  --config ../conf/gigapaxos.xdn.3way.cloudlab.properties \
  --experiment-id reconf_1000_request_mixed_TodoGolang_remote_fixed_3 \
  --consistency linearizable \
  --service todo_linearizable_golang \
  --target-host 10.10.1.1 \
  --target-port 2300 \
  --target-rate 1000 \
  --prealloc-vus 1500 \
  --max-vus 5000 \
  --warmup-tasks 50 \
  --duration 120 \
  --req-timeout 5s \
  --reconfig-schedule '{"60": {"NODES": ["AR0", "AR1", "AR2"]}}' \
  --csv-time-format unix_milli \
  2>&1 | tee reconf_1000_request_mixed_TodoGolang_remote_fixed_3.log
```
	
#### 10. RETRIEVE THE RESULT

FROM DRIVER :
```bash
rsync -azP username@clnode262.clemson.cloudlab.us:~/xdn/throughput_test/results_reconf_1000_request_mixed_TodoGolang_remote_fixed_3/ ./throughput_test/results_reconf_1000_request_mixed_TodoGolang_remote_fixed_3/

rsync -azP username@clnode262.clemson.cloudlab.us:~/xdn/debug_log/* ./debug_log/

rsync -azP username@clnode262.clemson.cloudlab.us:~/xdn/throughput_test/reconf_1000_request_mixed_TodoGolang_remote_fixed_3.log ./throughput_test/results_reconf_1000_request_mixed_TodoGolang_remote_fixed_3/
```

FROM RC and AR
```bash
OUT_DIR="debug_log/reconf_1000_request_mixed_TodoGolang_remote_fixed_2"; \
mkdir -p "$OUT_DIR"; \
nodes=("clnode346" "clnode381" "clnode383" "clnode334"); \
targets=("ar0" "ar1" "ar2" "rc0"); \
for i in "${!nodes[@]}"; do \
  scp -q -o StrictHostKeyChecking=no \
  "username@${nodes[$i]}.clemson.cloudlab.us:~/XdnGigapaxosApp/output/gigapaxos.log" \
  "$OUT_DIR/gigapaxos_${targets[$i]}.log"; \
done
```
#### 11. VISUALIZATION
```python
python parser.py results_reconf_1000_request_mixed_TodoGolang_remote_fixed_3 \
--model linearizable \
--detailed
```

```python
python visualize_results.py \
  --mode reconfiguration \
  --experiment results_reconf_1000_request_mixed_TodoGolang_remote_fixed_3 \
  --models linearizable \
	  --title "reconf_1000_request_mixed_TodoGolang_remote_fixed_3" \
  --output results_reconf_1000_request_mixed_TodoGolang_remote_fixed_3.png \
  --zoom
```