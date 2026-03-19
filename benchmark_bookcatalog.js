import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';

// ---------------------------------------------------------------------------
// Configuration via environment variables
// ---------------------------------------------------------------------------
const TARGET_HOST = __ENV.TARGET_HOST || 'localhost';
const TARGET_PORT = __ENV.TARGET_PORT || '2300';
const TOTAL_REQUESTS = parseInt(__ENV.TOTAL_REQUESTS) || 1000;
const WARMUP_BOOKS = parseInt(__ENV.WARMUP_BOOKS) || 10;

const BASE_URL = `http://${TARGET_HOST}:${TARGET_PORT}/api/books`;

// XDN header — required for XDN routing, ignored by Raft.
const HEADERS = {
    'Content-Type': 'application/json',
    'XDN': 'bookcatalog',
};

// ---------------------------------------------------------------------------
// k6 options: 1 VU, sequential, fixed number of iterations
// ---------------------------------------------------------------------------
export const options = {
    scenarios: {
        sequential_writes: {
            executor: 'per-vu-iterations',
            vus: 1,
            iterations: TOTAL_REQUESTS,
        },
    },
};

// ---------------------------------------------------------------------------
// setup — create books so the benchmark can PUT (update) them
// ---------------------------------------------------------------------------
export function setup() {
    console.log(`[setup] target:     ${BASE_URL}`);
    console.log(`[setup] requests:   ${TOTAL_REQUESTS}`);
    console.log(`[setup] warmup:     creating ${WARMUP_BOOKS} books`);

    const bookIds = [];

    for (let i = 1; i <= WARMUP_BOOKS; i++) {
        const payload = JSON.stringify({ title: `Book ${i}`, author: `Author ${i}` });
        const res = http.post(BASE_URL, payload, {
            headers: HEADERS,
            responseType: 'text', // need body to extract id
        });

        if (res.status === 200 || res.status === 201) {
            try {
                const body = JSON.parse(res.body);
                if (body.id !== undefined) bookIds.push(body.id);
            } catch (_) { /* ignore parse errors */ }
        } else {
            console.log(`[setup] WARN: book ${i} failed, status ${res.status}`);
        }
    }

    console.log(`[setup] warmup done: ${bookIds.length} books created, ids=[${bookIds.join(',')}]`);
    return { bookIds };
}

// ---------------------------------------------------------------------------
// default — sequential PUT /api/books/{id} (update in-place)
//
// Why PUT (update), not POST (create)?
//   - DB size stays constant -> no growing-table effect on latency
//   - Every PUT still goes through the full write path:
//       Raft:  raft.Apply (BoltDB fsync #1) -> FSM.Apply (SQLite fsync #2)
//       XDN:   Paxos consensus -> forward to Docker container
// ---------------------------------------------------------------------------
export default function (data) {
    const { bookIds } = data;
    const iter = exec.scenario.iterationInTest;

    // Round-robin across warmup books
    const bookId = bookIds[iter % bookIds.length];

    const payload = JSON.stringify({
        title: `Book ${bookId} iter ${iter}`,
        author: `Author ${bookId}`,
    });

    const res = http.put(`${BASE_URL}/${bookId}`, payload, { headers: HEADERS });

    check(res, { 'status 200': (r) => r.status === 200 });

    if (res.status !== 200 && iter % 100 === 0) {
        console.log(`[iter ${iter}] WARN: status ${res.status}`);
    }
}
