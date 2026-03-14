import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';
import exec from 'k6/execution';

export const successOps = new Counter('success_ops');

const TARGET_HOST = __ENV.XDN_TARGET_HOST || 'localhost';
const TARGET_PORT = __ENV.XDN_TARGET_PORT || '2300';
const SERVICE_NAME = __ENV.XDN_SERVICE_NAME || 'todo_sequential';
const TARGET_RATE = parseInt(__ENV.XDN_TARGET_RATE) || 250;
const LOAD_DURATION = __ENV.XDN_LOAD_DURATION || '180s';
const PREALLOC_VUS = parseInt(__ENV.XDN_PREALLOC_VUS) || 200;
const MAX_VUS = parseInt(__ENV.XDN_MAX_VUS) || 500;
const WARMUP_TASKS = parseInt(__ENV.XDN_WARMUP_TASKS) || 50;
const REQ_TIMEOUT = __ENV.XDN_REQ_TIMEOUT || '2s';
const WORKLOAD_MODE = (__ENV.XDN_WORKLOAD_MODE || 'mixed').trim().toLowerCase();
const READ_RATIO = parseFloat(__ENV.XDN_READ_RATIO || '0.8');

const TARGET_HOST_AFTER = __ENV.XDN_TARGET_HOST_AFTER || TARGET_HOST;
const TARGET_PORT_AFTER = __ENV.XDN_TARGET_PORT_AFTER || TARGET_PORT;

const BEFORE_URL = `http://${TARGET_HOST}:${TARGET_PORT}/api/todo/tasks`;
const AFTER_URL = `http://${TARGET_HOST_AFTER}:${TARGET_PORT_AFTER}/api/todo/tasks`;
const WARMUP_SLEEP_MS = 50;
const LOG_EVERY = 500;

export const options = {
    discardResponseBodies: true,
    scenarios: {
        load_test: {
            executor: 'constant-arrival-rate',
            rate: TARGET_RATE,
            timeUnit: '1s',
            duration: LOAD_DURATION,
            preAllocatedVUs: PREALLOC_VUS,
            maxVUs: MAX_VUS,
        },
    },
    thresholds: {
        // dropped_iterations: ['count==0'],
    },
};

// Todo API payload format: {"item": "task_X"}
function getTaskPayload(id) {
    return JSON.stringify({
        item: `task_${id}`
    });
}

// Warmup params - no timeout (use k6 default)
const warmupParams = {
    headers: { 'Content-Type': 'application/json', 'XDN': SERVICE_NAME },
};

// Load test params - with configured timeout
const params = {
    headers: { 'Content-Type': 'application/json', 'XDN': SERVICE_NAME },
    timeout: REQ_TIMEOUT,
};

if (!['read', 'write', 'mixed'].includes(WORKLOAD_MODE)) {
    throw new Error(
        `Invalid XDN_WORKLOAD_MODE=${WORKLOAD_MODE}. Expected one of: read, write, mixed`
    );
}

if (!Number.isFinite(READ_RATIO) || READ_RATIO < 0 || READ_RATIO > 1) {
    throw new Error(
        `Invalid XDN_READ_RATIO=${__ENV.XDN_READ_RATIO}. Expected a number between 0 and 1`
    );
}

export function setup() {
    console.log(`[setup] Configuration:`);
    console.log(`[setup] Target URL (before): ${BEFORE_URL}`);
    console.log(`[setup] Target URL (after):  ${AFTER_URL}`);
    console.log(`[setup] Service: ${SERVICE_NAME}`);
    console.log(`[setup] Target rate: ${TARGET_RATE} req/s`);
    console.log(`[setup] Duration: ${LOAD_DURATION}`);
    console.log(`[setup] Request timeout: ${REQ_TIMEOUT}`);
    console.log(`[setup] PreAllocated VUs: ${PREALLOC_VUS}`);
    console.log(`[setup] Max VUs: ${MAX_VUS}`);
    console.log(`[setup] Warmup tasks: ${WARMUP_TASKS}`);
    console.log(`[setup] Workload mode: ${WORKLOAD_MODE}`);
    if (WORKLOAD_MODE === 'mixed') {
        console.log(`[setup] Read ratio: ${READ_RATIO}`);
    }
    console.log(`[setup] Starting warmup: creating ${WARMUP_TASKS} tasks...`);

    let successCount = 0;
    let failCount = 0;

    for (let i = 1; i <= WARMUP_TASKS; i++) {
        const res = http.post(BEFORE_URL, getTaskPayload(i), warmupParams);

        if ([200, 201].includes(res.status)) {
            successCount++;
        } else {
            failCount++;
            console.log(`[setup] Failed to create task_${i}, status ${res.status}`);
        }

        if (i % 50 === 0) {
            console.log(`[setup] Progress: ${i}/${WARMUP_TASKS} tasks created`);
        }

        sleep(WARMUP_SLEEP_MS / 1000);
    }

    console.log(`[setup] Warmup complete: ${successCount} success, ${failCount} failed`);
    console.log('__WARMUP_COMPLETE__');

    return { warmupTasks: WARMUP_TASKS, successCount, failCount };
}

function isSuccess(status) {
    return status >= 200 && status < 300;
}

// Per-VU mutable state for target switching after reconfiguration
let switched = false;

function isFailure(status) {
    return status === 0 || status >= 500;
}

function getTargetUrl() {
    return switched ? AFTER_URL : BEFORE_URL;
}

function shouldSendReadRequest() {
    if (WORKLOAD_MODE === 'read') {
        return true;
    }
    if (WORKLOAD_MODE === 'write') {
        return false;
    }
    return Math.random() < READ_RATIO;
}

export default function (data) {
    // Each VU targets its own task ID (VU IDs are 1-indexed)
    // With constant-arrival-rate, VU IDs can go up to maxVUs (300)
    // Have 50 warmup tasks, so modulo is used to stay within range
    const taskId = ((exec.vu.idInTest - 1) % WARMUP_TASKS) + 1;
    const iter = exec.scenario.iterationInTest;
    const url = getTargetUrl();
    const isReadRequest = shouldSendReadRequest();

    if (isReadRequest) {
        // 80% READ - GET /api/todo/tasks returns all tasks
        const res = http.get(url, params);
        check(res, { 'Read OK': (r) => r.status === 200 });
        if (isSuccess(res.status)) {
            successOps.add(1);
        } else if (!switched && isFailure(res.status)) {
            switched = true;
            console.log(`[load][VU ${exec.vu.idInTest}][iter ${iter}] SWITCHED to ${AFTER_URL} (status ${res.status})`);
        }
        if (iter % LOG_EVERY === 0) {
            console.log(`[load][VU ${exec.vu.idInTest}][iter ${iter}] READ status ${res.status}`);
        }
    } else {
        // 20% POST - add/increment task counter
        const res = http.post(url, getTaskPayload(taskId), params);
        check(res, { 'Write OK': (r) => [200, 201].includes(r.status) });
        if (isSuccess(res.status)) {
            successOps.add(1);
        } else if (!switched && isFailure(res.status)) {
            switched = true;
            console.log(`[load][VU ${exec.vu.idInTest}][iter ${iter}] SWITCHED to ${AFTER_URL} (status ${res.status})`);
        }
        if (iter % LOG_EVERY === 0) {
            console.log(`[load][VU ${exec.vu.idInTest}][iter ${iter}] WRITE task_${taskId} status ${res.status}`);
        }
    }
}
