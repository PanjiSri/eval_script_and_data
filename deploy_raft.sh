#!/bin/bash
# Usage:
#   ./deploy_raft.sh build     # Build binary on all nodes
#   ./deploy_raft.sh start     # Start Raft cluster
#   ./deploy_raft.sh stop      # Stop Raft cluster
#   ./deploy_raft.sh status    # Check if nodes are running + who is leader
#   ./deploy_raft.sh clean     # Stop + remove data directories + logs
#   ./deploy_raft.sh logs      # Tail logs from all nodes
#   ./deploy_raft.sh sanity    # Run sanity checks against the cluster

# ============================================================
# Configuration — edit these to match your CloudLab setup
# ============================================================
USERNAME="${USERNAME:-panjisri}"
SSH_KEY="${SSH_KEY:-~/.ssh/id_cloudlab}"
SSH_OPTS="-o StrictHostKeyChecking=no -i $SSH_KEY"

NODE1_IP="10.10.1.1"
NODE2_IP="10.10.1.2"
NODE3_IP="10.10.1.3"

ALL_IPS=("$NODE1_IP" "$NODE2_IP" "$NODE3_IP")
NODE_IDS=("node1" "node2" "node3")
HTTP_PORTS=("8001" "8002" "8003")

RAFT_PORT=7000
RAFT_PEERS="node1=${NODE1_IP}:${RAFT_PORT},node2=${NODE2_IP}:${RAFT_PORT},node3=${NODE3_IP}:${RAFT_PORT}"

# Remote paths:
#   Source:  ~/xdn/services/bookcatalog-raft  (already there from XDN deploy)
#   Work:    ~/raft-eval/                      (binary, data, logs)

# ============================================================
# Helper
# ============================================================
ssh_cmd() {
    local ip="$1"
    shift
    ssh $SSH_OPTS "$USERNAME@$ip" "$@"
}

log() {
    echo "[$(date '+%H:%M:%S')] $*"
}

# ============================================================
# Commands
# ============================================================

do_build() {
    log "Building bookcatalog-raft on all nodes..."
    for i in "${!ALL_IPS[@]}"; do
        local ip="${ALL_IPS[$i]}"
        log "  Building on $ip..."
        ssh_cmd "$ip" bash -s <<'REMOTE_SCRIPT'
            set -e
            if ! dpkg -s libsqlite3-dev &>/dev/null; then
                sudo apt-get update -qq && sudo apt-get install -y -qq gcc libsqlite3-dev
            fi

            SRC_DIR=~/xdn/services/bookcatalog-raft
            WORK_DIR=~/raft-eval

            mkdir -p "$WORK_DIR"
            cd "$SRC_DIR"
            CGO_ENABLED=1 go build -o "$WORK_DIR/bookcatalog-raft" .
            echo "Binary built: $WORK_DIR/bookcatalog-raft"
REMOTE_SCRIPT
    done
    log "Build complete on all nodes."
}

do_start() {
    log "Starting Raft cluster..."
    for i in "${!ALL_IPS[@]}"; do
        local ip="${ALL_IPS[$i]}"
        local node_id="${NODE_IDS[$i]}"
        local port="${HTTP_PORTS[$i]}"

        log "  Starting $node_id on $ip (HTTP port $port)..."
        ssh_cmd "$ip" bash -s <<REMOTE_SCRIPT
            cd ~/raft-eval

            # Check if already running
            if pgrep -f '[b]ookcatalog-raft' > /dev/null 2>&1; then
                echo "$node_id is already running on $ip"
                exit 0
            fi

            NODE_ID=$node_id \
            RAFT_ADDR=0.0.0.0:$RAFT_PORT \
            RAFT_PEERS="$RAFT_PEERS" \
            RAFT_DIR=./raft-data \
            DB_PATH=./data \
            PORT=$port \
            nohup ./bookcatalog-raft > bookcatalog-raft.log 2>&1 &
            disown

            sleep 0.5
            if pgrep -f '[b]ookcatalog-raft' > /dev/null 2>&1; then
                echo "$node_id started (PID \$!)"
            else
                echo "ERROR: $node_id failed to start. Check log:"
                tail -5 bookcatalog-raft.log 2>/dev/null
                exit 1
            fi
REMOTE_SCRIPT
    done
    log "Cluster started. Waiting for leader election..."
    sleep 3
    do_status
}

do_stop() {
    log "Stopping Raft cluster..."
    for i in "${!ALL_IPS[@]}"; do
        local ip="${ALL_IPS[$i]}"
        local node_id="${NODE_IDS[$i]}"

        log "  Stopping $node_id on $ip..."
        ssh_cmd "$ip" "pkill -f '[b]ookcatalog-raft' 2>/dev/null; true" || true
    done
    sleep 1
    log "Cluster stopped."
}

do_status() {
    log "Checking cluster status..."
    for i in "${!ALL_IPS[@]}"; do
        local ip="${ALL_IPS[$i]}"
        local node_id="${NODE_IDS[$i]}"
        local port="${HTTP_PORTS[$i]}"

        local running="STOPPED"
        if ssh_cmd "$ip" "pgrep -f '[b]ookcatalog-raft'" > /dev/null 2>&1; then
            running="RUNNING"
        fi

        local role=""
        if [ "$running" = "RUNNING" ]; then
            local state
            state=$(ssh_cmd "$ip" "grep -oE 'entering (leader|follower|candidate) state' ~/raft-eval/bookcatalog-raft.log 2>/dev/null | tail -1" || true)
            if [[ "$state" == *"leader"* ]]; then
                role="(LEADER)"
            elif [[ "$state" == *"follower"* ]]; then
                role="(follower)"
            elif [[ "$state" == *"candidate"* ]]; then
                role="(candidate)"
            else
                role="(unknown)"
            fi
        fi

        echo "  $node_id ($ip:$port) — $running $role"
    done
}

do_clean() {
    do_stop
    log "Cleaning data directories and logs..."
    for i in "${!ALL_IPS[@]}"; do
        local ip="${ALL_IPS[$i]}"
        local node_id="${NODE_IDS[$i]}"

        log "  Cleaning $node_id on $ip..."
        ssh_cmd "$ip" "rm -rf ~/raft-eval/raft-data ~/raft-eval/data ~/raft-eval/bookcatalog-raft.log" || true
    done
    log "Clean complete."
}

do_logs() {
    local node_idx="${1:-all}"

    if [ "$node_idx" = "all" ]; then
        for i in "${!ALL_IPS[@]}"; do
            local ip="${ALL_IPS[$i]}"
            local node_id="${NODE_IDS[$i]}"
            echo "=== $node_id ($ip) ==="
            ssh_cmd "$ip" "tail -20 ~/raft-eval/bookcatalog-raft.log 2>/dev/null || echo 'No log file'"
            echo ""
        done
    else
        if [ "$node_idx" -ge "${#ALL_IPS[@]}" ] 2>/dev/null; then
            echo "Invalid node index: $node_idx (use 0, 1, or 2)"
            exit 1
        fi
        local ip="${ALL_IPS[$node_idx]}"
        ssh_cmd "$ip" "tail -f ~/raft-eval/bookcatalog-raft.log"
    fi
}

do_sanity_check() {
    local failures=0
    local leader_ip="" leader_port="" follower_ip="" follower_port=""
    local epoch
    epoch=$(date +%s)
    local test_title="SanityCheck_${epoch}"

    # Step 1: Discover leader by probing each node with a write
    log "Step 1: Discovering leader..."
    local probe_id=""
    for i in "${!ALL_IPS[@]}"; do
        local ip="${ALL_IPS[$i]}"
        local port="${HTTP_PORTS[$i]}"
        local http_code body
        body=$(curl -s -o /dev/null -w "%{http_code}" \
            --connect-timeout 5 --max-time 10 \
            -X POST "http://${ip}:${port}/api/books" \
            -H "Content-Type: application/json" \
            -d '{"title":"probe_leader","author":"probe"}')
        if [ "$body" = "200" ]; then
            leader_ip="$ip"
            leader_port="$port"
            # Fetch the probe book ID so we can clean it up
            local probe_resp
            probe_resp=$(curl -s --connect-timeout 5 --max-time 10 \
                "http://${ip}:${port}/api/books")
            probe_id=$(echo "$probe_resp" | python3 -c "
import sys, json
books = json.load(sys.stdin)
for b in books:
    if b.get('title') == 'probe_leader':
        print(b['id']); break
" 2>/dev/null || true)
        elif [ -z "$follower_ip" ]; then
            follower_ip="$ip"
            follower_port="$port"
        fi
    done

    # Clean up probe book
    if [ -n "$probe_id" ] && [ -n "$leader_ip" ]; then
        curl -s --connect-timeout 5 --max-time 10 \
            -X DELETE "http://${leader_ip}:${leader_port}/api/books/${probe_id}" > /dev/null 2>&1
    fi

    if [ -n "$leader_ip" ]; then
        log "PASS: Leader discovered at ${leader_ip}:${leader_port}"
    else
        log "FAIL: Could not discover leader"
        failures=$((failures + 1))
        echo ""
        log "Summary: ${failures} failure(s)"
        return $failures
    fi

    # Ensure we have a follower
    if [ -z "$follower_ip" ]; then
        for i in "${!ALL_IPS[@]}"; do
            if [ "${ALL_IPS[$i]}" != "$leader_ip" ]; then
                follower_ip="${ALL_IPS[$i]}"
                follower_port="${HTTP_PORTS[$i]}"
                break
            fi
        done
    fi

    # Step 2: Write via leader
    log "Step 2: Writing test book via leader..."
    local create_resp create_code
    create_resp=$(curl -s -w "\n%{http_code}" \
        --connect-timeout 5 --max-time 10 \
        -X POST "http://${leader_ip}:${leader_port}/api/books" \
        -H "Content-Type: application/json" \
        -d "{\"title\":\"${test_title}\",\"author\":\"AutomatedTest\"}")
    create_code=$(echo "$create_resp" | tail -1)
    local create_body
    create_body=$(echo "$create_resp" | sed '$d')

    if [ "$create_code" = "200" ]; then
        log "PASS: Write via leader returned HTTP 200"
    else
        log "FAIL: Write via leader returned HTTP ${create_code} (expected 200)"
        failures=$((failures + 1))
    fi

    local book_id
    book_id=$(echo "$create_body" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || true)

    # Step 3: Write to non-leader (expect 503)
    log "Step 3: Writing to follower (expect rejection)..."
    local follower_resp follower_code follower_headers
    follower_headers=$(curl -s -D - -o /dev/null -w "\n%{http_code}" \
        --connect-timeout 5 --max-time 10 \
        -X POST "http://${follower_ip}:${follower_port}/api/books" \
        -H "Content-Type: application/json" \
        -d '{"title":"should_fail","author":"test"}')
    follower_code=$(echo "$follower_headers" | tail -1)

    if [ "$follower_code" = "503" ]; then
        if echo "$follower_headers" | grep -qi "X-Raft-Leader"; then
            log "PASS: Follower returned HTTP 503 with X-Raft-Leader header"
        else
            log "PASS: Follower returned HTTP 503 (X-Raft-Leader header not found, but status correct)"
        fi
    else
        log "FAIL: Follower returned HTTP ${follower_code} (expected 503)"
        failures=$((failures + 1))
    fi

    # Step 4: Verify replication on all nodes
    log "Step 4: Verifying replication (waiting 1s)..."
    sleep 1
    for i in "${!ALL_IPS[@]}"; do
        local ip="${ALL_IPS[$i]}"
        local port="${HTTP_PORTS[$i]}"
        local node_id="${NODE_IDS[$i]}"
        local get_resp
        get_resp=$(curl -s --connect-timeout 5 --max-time 10 \
            "http://${ip}:${port}/api/books")
        if echo "$get_resp" | grep -q "$test_title"; then
            log "PASS: ${node_id} (${ip}:${port}) has replicated test book"
        else
            log "FAIL: ${node_id} (${ip}:${port}) missing test book"
            failures=$((failures + 1))
        fi
    done

    # Step 5: Cleanup — delete the test book via leader
    log "Step 5: Cleaning up test book..."
    if [ -n "$book_id" ]; then
        local del_code
        del_code=$(curl -s -o /dev/null -w "%{http_code}" \
            --connect-timeout 5 --max-time 10 \
            -X DELETE "http://${leader_ip}:${leader_port}/api/books/${book_id}")
        sleep 1
        # Verify deletion
        local verify_resp
        verify_resp=$(curl -s --connect-timeout 5 --max-time 10 \
            "http://${leader_ip}:${leader_port}/api/books")
        if echo "$verify_resp" | grep -q "$test_title"; then
            log "FAIL: Test book still present after deletion"
            failures=$((failures + 1))
        else
            log "PASS: Test book cleaned up successfully"
        fi
    else
        log "FAIL: No book ID to clean up (create may have failed)"
        failures=$((failures + 1))
    fi

    # Summary
    echo ""
    if [ "$failures" -eq 0 ]; then
        log "Summary: All sanity checks PASSED"
    else
        log "Summary: ${failures} check(s) FAILED"
    fi
    return $failures
}

# ============================================================
# Main
# ============================================================
case "${1:-help}" in
    build)         do_build ;;
    start)         do_start ;;
    stop)          do_stop ;;
    status)        do_status ;;
    clean)         do_clean ;;
    logs)          do_logs "${2:-all}" ;;
    sanity|check)  do_sanity_check ;;
    *)
        echo "Usage: $0 {build|start|stop|status|clean|logs|sanity}"
        echo ""
        echo "  build   — Build binary on all 3 nodes"
        echo "  start   — Start Raft cluster"
        echo "  stop    — Stop all nodes"
        echo "  status  — Check if nodes are running + who is leader"
        echo "  clean   — Stop + remove data dirs + logs"
        echo "  logs    — Show logs (or: logs 0|1|2 for specific node)"
        echo "  sanity  — Run sanity checks (write/read/replicate/cleanup)"
        exit 1
        ;;
esac
