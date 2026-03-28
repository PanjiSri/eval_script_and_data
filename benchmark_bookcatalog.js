import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';
import exec from 'k6/execution';

export const successOps = new Counter('success_ops');

const TARGET_HOST = __ENV.XDN_TARGET_HOST || 'localhost';
const TARGET_PORT = __ENV.XDN_TARGET_PORT || '2300';
const SERVICE_NAME = __ENV.XDN_SERVICE_NAME || 'bookcatalog';
const TARGET_RATE = parseInt(__ENV.XDN_TARGET_RATE) || 250;
const LOAD_DURATION = __ENV.XDN_LOAD_DURATION || '180s';
const PREALLOC_VUS = parseInt(__ENV.XDN_PREALLOC_VUS) || 200;
const MAX_VUS = parseInt(__ENV.XDN_MAX_VUS) || 500;
const WARMUP_BOOKS = parseInt(__ENV.XDN_WARMUP_TASKS) || 50;
const REQ_TIMEOUT = __ENV.XDN_REQ_TIMEOUT || '2s';
const WORKLOAD_MODE = (__ENV.XDN_WORKLOAD_MODE || 'mixed').trim().toLowerCase();
const READ_RATIO = parseFloat(__ENV.XDN_READ_RATIO || '0.8');

const TARGET_HOST_AFTER = __ENV.XDN_TARGET_HOST_AFTER || TARGET_HOST;
const TARGET_PORT_AFTER = __ENV.XDN_TARGET_PORT_AFTER || TARGET_PORT;

// Base URLs point to /api/books (not /api/todo/tasks)
const BEFORE_BASE_URL = `http://${TARGET_HOST}:${TARGET_PORT}/api/books`;
const AFTER_BASE_URL = `http://${TARGET_HOST_AFTER}:${TARGET_PORT_AFTER}/api/books`;
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
    thresholds: {},
};

// Bookcatalog API payload format: {"title": "Book X", "author": "Author X"}
function getBookPayload(id) {
    return JSON.stringify({
        title: `Book ${id}`,
        author: `Author ${id}`,
    });
}

// Warmup params - responseType: 'text' to capture response body and extract IDs
const warmupParams = {
    headers: { 'Content-Type': 'application/json', 'XDN': SERVICE_NAME },
    responseType: 'text',
};

// Load test params - with configured timeout, response body discarded
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
    console.log(`[setup] Target URL (before): ${BEFORE_BASE_URL}`);
    console.log(`[setup] Target URL (after):  ${AFTER_BASE_URL}`);
    console.log(`[setup] Service: ${SERVICE_NAME}`);
    console.log(`[setup] Target rate: ${TARGET_RATE} req/s`);
    console.log(`[setup] Duration: ${LOAD_DURATION}`);
    console.log(`[setup] Request timeout: ${REQ_TIMEOUT}`);
    console.log(`[setup] PreAllocated VUs: ${PREALLOC_VUS}`);
    console.log(`[setup] Max VUs: ${MAX_VUS}`);
    console.log(`[setup] Warmup books: ${WARMUP_BOOKS}`);
    console.log(`[setup] Workload mode: ${WORKLOAD_MODE}`);
    if (WORKLOAD_MODE === 'mixed') {
        console.log(`[setup] Read ratio: ${READ_RATIO}`);
    }
    console.log(`[setup] Starting warmup: creating ${WARMUP_BOOKS} books...`);

    const bookIds = [];
    let successCount = 0;
    let failCount = 0;

    for (let i = 1; i <= WARMUP_BOOKS; i++) {
        // POST to create new books during warmup; capture IDs from response body
        const res = http.post(BEFORE_BASE_URL, getBookPayload(i), warmupParams);

        if ([200, 201].includes(res.status)) {
            successCount++;
            try {
                const body = JSON.parse(res.body);
                if (body.id !== undefined) {
                    bookIds.push(body.id);
                }
            } catch (e) {
                console.log(`[setup] Failed to parse response for book_${i}: ${e}`);
            }
        } else {
            failCount++;
            console.log(`[setup] Failed to create book_${i}, status ${res.status}`);
        }

        if (i % 50 === 0) {
            console.log(`[setup] Progress: ${i}/${WARMUP_BOOKS} books created`);
        }

        sleep(WARMUP_SLEEP_MS / 1000);
    }

    console.log(`[setup] Warmup complete: ${successCount} success, ${failCount} failed`);
    const preview = bookIds.slice(0, 5).join(', ') + (bookIds.length > 5 ? '...' : '');
    console.log(`[setup] Captured ${bookIds.length} book IDs: [${preview}]`);
    console.log('__WARMUP_COMPLETE__');

    return { bookIds, warmupBooks: WARMUP_BOOKS, successCount, failCount };
}

function isSuccess(status) {
    return status >= 200 && status < 300;
}

// Per-VU mutable state for target switching after reconfiguration
let switched = false;

function isFailure(status) {
    return status === 0 || status >= 500;
}

function getBaseUrl() {
    return switched ? AFTER_BASE_URL : BEFORE_BASE_URL;
}

function shouldSendReadRequest() {
    if (WORKLOAD_MODE === 'read') return true;
    if (WORKLOAD_MODE === 'write') return false;
    return Math.random() < READ_RATIO;
}

export default function (data) {
    const { bookIds } = data;
    const vuId = exec.vu.idInTest;
    const iter = exec.scenario.iterationInTest;
    const baseUrl = getBaseUrl();
    const isReadRequest = shouldSendReadRequest();

    // Round-robin book ID selection from IDs captured during warmup.
    // Fallback to sequential modulo if warmup IDs were not captured.
    let bookId;
    if (bookIds && bookIds.length > 0) {
        bookId = bookIds[(vuId - 1) % bookIds.length];
    } else {
        bookId = ((vuId - 1) % WARMUP_BOOKS) + 1;
    }

    if (isReadRequest) {
        // READ - GET /api/books/{bookId} (returns single book)
        const res = http.get(`${baseUrl}/${bookId}`, params);
        check(res, { 'Read OK': (r) => r.status === 200 });
        if (isSuccess(res.status)) {
            successOps.add(1);
        } else if (!switched && isFailure(res.status)) {
            switched = true;
            console.log(`[load][VU ${vuId}][iter ${iter}] SWITCHED to ${AFTER_BASE_URL} (status ${res.status})`);
        }
        if (iter % LOG_EVERY === 0) {
            console.log(`[load][VU ${vuId}][iter ${iter}] READ status ${res.status}`);
        }
    } else {
        // WRITE - PUT /api/books/{id} (update in-place, DB size stays constant)
        const url = `${baseUrl}/${bookId}`;
        const res = http.put(url, getBookPayload(bookId), params);
        check(res, { 'Write OK': (r) => [200, 201].includes(r.status) });
        if (isSuccess(res.status)) {
            successOps.add(1);
        } else if (!switched && isFailure(res.status)) {
            switched = true;
            console.log(`[load][VU ${vuId}][iter ${iter}] SWITCHED to ${AFTER_BASE_URL} (status ${res.status})`);
        }
        if (iter % LOG_EVERY === 0) {
            console.log(`[load][VU ${vuId}][iter ${iter}] WRITE book_${bookId} status ${res.status}`);
        }
    }
}
