**RAFT**

```bash
./deploy_raft.sh build
```

```bash
./deploy_raft.sh start
```

```bash
./deploy_raft.sh status 
```

```bash
./deploy_raft.sh sanity
```

```bash
TARGET_HOST=10.10.1.1 TARGET_PORT=8001 TOTAL_REQUESTS=10000 WARMUP_BOOKS=50 k6 run --out csv=raw_raft_remote.csv benchmark_bookcatalog.js
```

```bash
./deploy_raft.sh clean
```

```
rsync -azP panjisri@clnode327.clemson.cloudlab.us:~/xdn/fsync_evaluation/ ./fsync_evaluation/
```

```bash
python3 parser.py --input raw_raft_remote.csv --output latency_raft_remote.csv
```

```
python3 plot.py 1 latency_raft_remote.csv latency_raft_remote.png
```

**XDN**

```bash
./bin/gpServer.sh -DgigapaxosConfig=conf/gigapaxos.xdn.3way.cloudlab.properties start all
```

```bash
export XDN_CONTROL_PLANE=10.10.1.4
```

```bash
xdn launch bookcatalog --image=fadhilkurnia/xdn-bookcatalog --state=/app/data/ --deterministic=true
```

```bash
for host in 10.10.1.1 10.10.1.2 10.10.1.3; do
  echo "Host $host:"
  curl -s "http://$host:2300/api/v2/services/bookcatalog/replica/info" \
    -H "XDN: bookcatalog" |
    grep -o '"role":"[^"]*"'
done
```

```bash
TARGET_HOST=10.10.1.1 TARGET_PORT=2300 TOTAL_REQUESTS=10000 WARMUP_BOOKS=50 k6 run --out csv=raw_xdn_remote.csv benchmark_bookcatalog.js
```

```
rsync -azP panjisri@clnode327.clemson.cloudlab.us:~/xdn/fsync_evaluation/ ./fsync_evaluation/
```

```bash
python3 parser.py --input raw_xdn_remote.csv --output latency_xdn_remote.csv
```

```
python3 plot.py 1 latency_xdn_remote.csv latency_xdn_remote.png
```

```bash
SSH_KEY_PATH=~/.ssh/id_cloudlab \
GP_USERNAME=panjisri \
  ./bin/gpServer.sh \
    -DgigapaxosConfig=conf/gigapaxos.xdn.3way.cloudlab.properties \
    forceclear all
    
for h in 10.10.1.1 10.10.1.2 10.10.1.3 10.10.1.4; do
    ssh -i ~/.ssh/id_cloudlab panjisri@$h "sudo rm -rf /tmp/gigapaxos /tmp/xdn"
  done
```

**BOTH**
```python
python3 plot.py 2 latency_raft_remote.csv latency_xdn_remote.csv CDF_Graph_remote.png
```