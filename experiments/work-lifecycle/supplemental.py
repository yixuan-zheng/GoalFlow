"""Supplemental probes of concurrency and invalid inputs, beyond frozen cases."""
from concurrent.futures import ThreadPoolExecutor
import json
import signal
import subprocess
import sys

from scenarios import HERE


def race(c, requests):
    def invoke(request):
        request = {"work_id": "assignment", **request}
        result = subprocess.run([sys.executable, str(HERE / "command.py"), c.backend, str(c.root / "store")],
                                input=json.dumps(request), text=True, capture_output=True, timeout=45)
        return request, result
    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        outcomes = list(pool.map(invoke, requests))
    responses = []
    for request, result in outcomes:
        c.record(concurrent_request=request, returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
        c.check(result.returncode == 0, "concurrent command process successful: " + result.stderr[-1000:])
        response = json.loads(result.stdout)
        c.invariants(response["state"])
        responses.append(response)
    c.call("inspect")
    return responses


def exclusive_ownership(c):
    c.create()
    results = race(c, [{"op": "start", "attempt_id": f"contender-{i}", "revision": 1, "now": 0} for i in range(8)])
    c.check(sum(r["ok"] for r in results) == 1 and len(c.state["attempts"]) == 1,
            "eight simultaneous unique claims admit exactly one owner")
    c.complete()


def simultaneous_duplicate_events(c):
    c.create()
    c.start()
    c.wait()
    event = {"op": "event", "event_id": "parallel-result", "attempt_id": "a1", "revision": 1,
             "key": c.domain + ":result", "payload": {"result": "ready"}}
    results = race(c, [event for _ in range(8)])
    c.check(all(r["ok"] for r in results), "simultaneous duplicate events all acknowledge safely")
    c.check(len(c.state["events"]) == len(c.state["wakes"]) == 1, "parallel duplicate delivery produces one event and wake")
    c.schedule()
    c.complete()


def invalid_inputs(c):
    c.create()
    c.start()
    before = json.loads(json.dumps(c.state))
    commands = [
        ("unknown", {}),
        ("start", {"attempt_id": "bad", "revision": True, "now": 0}),
        ("start", {"attempt_id": "bad", "revision": 1, "now": 0, "lease_seconds": 0}),
        ("finish", {"attempt_id": "a1", "revision": 1, "kind": "wait", "reason": "empty cause", "wait_key": ""}),
        ("finish", {"attempt_id": "a1", "revision": 1, "kind": "complete", "reason": "truthy claim", "authorized": 1, "evidence": {"claimed": True}}),
        ("finish", {"attempt_id": "a1", "revision": 1, "kind": "complete", "reason": "missing evidence", "authorized": True, "evidence": {}}),
        ("event", {"event_id": "unknown", "attempt_id": "not-known", "revision": 1, "key": "x", "payload": {}}),
        ("event", {"event_id": "future", "attempt_id": "a1", "revision": 2, "key": "x", "payload": {}}),
        ("revise", {"revision": 3, "reason": "skip revision"}),
        ("ack", {"wake_id": "not-known"}),
    ]
    for op, fields in commands:
        c.call(op, expected=False, **fields)
        c.check(c.state == before, "invalid request leaves authoritative state unchanged")
    c.complete()


def revise_waiting(c):
    c.create()
    c.start()
    c.app.artifact("committed-v1", 1)
    c.event("unmatched", key="other-result")
    c.wait()
    c.call("revise", revision=2, reason="new requirements while waiting")
    c.check(c.state["events"][0]["status"] == "stale", "revision invalidates old buffered event")
    c.check(c.state["wait_key"] is None, "revision clears old waiting cause")
    c.event("late", revision=1)
    c.check(c.state["events"][-1]["status"] == "stale", "old waiting result stays obsolete")
    c.schedule()
    c.complete("repaired-v2", 2)


def cancellation_delivery_race(c):
    c.create()
    c.start()
    c.finish("continue")
    wake = c.pending()[0]
    results = race(c, [
        {"op": "cancel", "reason": "cancel during delivery"},
        {"op": "start", "attempt_id": "delivery:" + wake["id"], "revision": 1, "now": 10},
    ])
    c.check(results[0]["ok"], "cancellation accepted regardless of admission order")
    c.check(c.state["status"] == "cancelled" and c.state["active_attempt"] is None and not c.pending(),
            "cancellation dominates a racing continuation delivery")


def completion_revision_race(c):
    c.create()
    c.start()
    path = c.app.artifact("valid-v1")
    proof = c.proof(path)
    results = race(c, [
        {"op": "finish", "attempt_id": "a1", "revision": 1, "kind": "complete", "reason": "verified", **proof},
        {"op": "revise", "revision": 2, "reason": "scope changed"},
    ])
    c.check(sum(r["ok"] for r in results) == 1, "completion and revision have one serializable winner")
    if c.state["status"] == "ready":
        c.check(c.state["revision"] == 2, "winning revision fences old completion")
        c.schedule()
        c.complete("valid-v2", 2)
    else:
        c.check(c.state["status"] == "completed" and c.state["revision"] == 1,
                "completion before revision is valid and later revision rejected")


def precommit_sqlite_crash(c):
    c.create()
    c.start()
    before = json.loads(json.dumps(c.state))
    request = {"work_id": "assignment", "op": "finish", "attempt_id": "a1", "revision": 1,
               "kind": "continue", "reason": "inject crash after SQL insert before commit"}
    result = subprocess.run([sys.executable, str(HERE / "sqlite_fault.py"), c.backend, str(c.root / "store")],
                            input=json.dumps(request), capture_output=True, text=True, timeout=30)
    c.record(storage_fault="SIGKILL after INSERT executed but before transaction commit", request=request,
             returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
    c.check(result.returncode == -signal.SIGKILL, "process killed inside actual SQLite write transaction")
    c.call("inspect")
    c.check(c.state == before, "uncommitted disposition and wake both roll back")
    c.finish("continue")
    c.schedule()
    c.complete()


SUPPLEMENTAL = {f.__name__: f for f in (exclusive_ownership, simultaneous_duplicate_events, invalid_inputs,
                                        revise_waiting, cancellation_delivery_race, completion_revision_race)}
SQLITE_ONLY = {"precommit_sqlite_crash": precommit_sqlite_crash}
