"""Black-box observable scenarios; never imported by a lifecycle backend."""
import hashlib
import json
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

from applications import Application

HERE = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise AssertionError(message)


class Case:
    def __init__(self, backend, domain, name, root, manager=None):
        self.backend, self.domain, self.name = backend, domain, name
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=False)
        self.manager = manager
        self.app = Application(domain, self.root)
        self.trace = (self.root / "trace.jsonl").open("w")
        self.assertions = 0
        self.state = None

    def record(self, **entry):
        self.trace.write(json.dumps({"time": datetime.now(timezone.utc).isoformat(), **entry}, sort_keys=True) + "\n")
        self.trace.flush()

    def check(self, condition, message):
        self.assertions += 1
        self.record(assertion=message, passed=bool(condition))
        require(condition, message)

    def invariants(self, state):
        if state is None:
            return
        attempts = state["attempts"]
        active = [a for a in attempts if a["status"] == "running"]
        self.check(len(active) <= 1, "at most one running attempt")
        self.check((state["status"] == "running") == (state["active_attempt"] is not None), "ownership matches running work")
        if state["active_attempt"] is not None:
            self.check(len(active) == 1 and active[0]["id"] == state["active_attempt"] and
                       active[0]["revision"] == state["revision"], "owner is a current running attempt")
        self.check(len({a["id"] for a in attempts}) == len(attempts), "attempt IDs unique")
        self.check(len({e["id"] for e in state["events"]}) == len(state["events"]), "event IDs unique")
        self.check(len({w["id"] for w in state["wakes"]}) == len(state["wakes"]), "wake IDs unique")
        consumed = [e["attempt_id"] for e in state["events"] if e["status"] == "consumed"]
        self.check(len(consumed) == len(set(consumed)), "at most one result consumed for a finite attempt wait")
        if state["status"] == "waiting":
            self.check(bool(state["wait_key"]), "waiting has an explicit cause")
        else:
            self.check(state["wait_key"] is None, "nonwaiting state has no live wait key")

    def call(self, op, expected=True, kill=False, **fields):
        request = {"op": op, "work_id": "assignment", **fields}
        args = [sys.executable, str(HERE / "command.py"), self.backend, str(self.root / "store")]
        if kill:
            args.append("--kill-after")
        process = subprocess.run(args, input=json.dumps(request), text=True, capture_output=True, timeout=45)
        self.record(request=request, returncode=process.returncode, stdout=process.stdout, stderr=process.stderr,
                    client_kill_after_commit=kill)
        if kill:
            self.check(process.returncode == -signal.SIGKILL, "client actually died by SIGKILL after durable command")
            return None
        self.check(process.returncode == 0, "command client exited successfully: " + process.stderr[-1000:])
        response = json.loads(process.stdout)
        self.check(response["ok"] is expected, f"{op} accepted={expected}, got {response['code']}")
        self.state = response["state"]
        self.invariants(self.state)
        return response

    def create(self):
        self.call("create", domain=self.domain, revision=1)
        self.check(self.state["status"] == "ready" and not self.state["attempts"], "new assignment ready without an execution")

    def start(self, attempt="a1", revision=1, now=0, **extra):
        return self.call("start", attempt_id=attempt, revision=revision, now=now, **extra)

    def finish(self, kind, attempt=None, revision=None, expected=True, kill=False, **extra):
        attempt = attempt or self.state["active_attempt"]
        revision = revision or self.state["revision"]
        return self.call("finish", attempt_id=attempt, revision=revision, kind=kind,
                         reason=extra.pop("reason", kind + " scripted assignment"), expected=expected, kill=kill, **extra)

    def event(self, identity="result1", attempt="a1", revision=1, key=None, **extra):
        return self.call("event", event_id=identity, key=key or self.domain + ":result", revision=revision,
                         attempt_id=attempt, payload=extra.pop("payload", {"result": "available"}), **extra)

    def wait(self, attempt="a1", key=None):
        self.finish("wait", attempt=attempt, wait_key=key or self.domain + ":result")

    def pending(self):
        return [w for w in self.state["wakes"] if w["status"] == "pending"]

    def schedule(self, now=10):
        """External scheduler: stable delivery identity, then ack, no state machine."""
        self.call("inspect")
        ready = self.pending()
        self.check(self.state["status"] == "ready" and len(ready) == 1, "exactly one runnable continuation intent")
        wake = ready[0]
        attempt = "delivery:" + wake["id"]
        self.start(attempt, self.state["revision"], now)
        self.call("ack", wake_id=wake["id"])
        return attempt

    def proof(self, path, revision=1, reviewer="maintainer"):
        decision = self.app.verify(path, revision, reviewer)
        file = self.root / "artifacts" / (path.stem + "-" + reviewer + "-verification-v" + str(revision) + ".json")
        file.write_text(json.dumps(decision, indent=2) + "\n")
        self.record(application_verification=decision)
        return decision

    def complete(self, label="repaired", revision=None):
        revision = revision or self.state["revision"]
        path = self.app.artifact(label, revision, valid=True)
        proof = self.proof(path, revision)
        self.check(proof["authorized"], "independent application verifier authorizes completion")
        self.finish("complete", **proof)
        self.check(self.state["status"] == "completed" and self.state["active_attempt"] is None, "verified work completed and ownership released")


def normal_continuation(c):
    c.create()
    c.start()
    partial = c.app.artifact("initial", valid=False)
    c.check(not c.proof(partial)["authorized"], "first artifact fails actual verification")
    c.wait()
    c.check(c.state["status"] == "waiting" and c.state["active_attempt"] is None, "attempt ended while work waits")
    c.event(payload={"result": "failed_checks" if c.domain == "coding" else "background_ready"})
    c.check(c.state["status"] == "ready", "result resumes persistent assignment")
    c.schedule()
    c.complete()


def early_event(c):
    c.create()
    c.start()
    c.app.artifact("partial", valid=False)
    c.event()
    c.check(c.state["status"] == "running" and c.state["events"][0]["status"] == "buffered", "early result retained without stealing ownership")
    c.wait()
    c.check(c.state["status"] == "ready" and c.state["events"][0]["status"] == "consumed", "wait consumes already arrived result")
    c.schedule()
    c.complete()


def duplicate_event(c):
    c.create()
    c.start()
    c.event()
    c.event()
    c.check(len(c.state["events"]) == 1 and not c.state["wakes"], "buffered duplicate causes no extra event or wake")
    c.wait()
    c.event()
    c.check(len(c.state["events"]) == len(c.state["wakes"]) == 1, "consumed duplicate causes no extra event or wake")
    c.event(payload={"result": "conflicting"}, expected=False)
    c.check(len(c.state["events"]) == len(c.state["wakes"]) == 1, "conflicting duplicate rejected without mutation")
    c.schedule()
    c.complete()


def revision_after_artifact(c):
    c.create()
    c.start()
    committed = c.app.artifact("committed-v1", revision=1, valid=True)
    proof = c.proof(committed, 1)
    c.check(committed.is_file() and proof["authorized"], "valid v1 artifact exists before requirements change")
    prior_hash = hashlib.sha256(committed.read_bytes()).hexdigest()
    c.record(committed_artifact_before_revision=str(committed), sha256=prior_hash)
    c.call("revise", revision=2, reason="member discount" if c.domain == "coding" else "north-only scope")
    c.check(c.state["status"] == "ready" and c.state["revision"] == 2, "new specification invalidates old owner")
    c.finish("complete", attempt="a1", revision=1, expected=False, **proof)
    c.check(c.state["status"] != "completed", "obsolete verified artifact cannot complete revised work")
    c.event("old-v1-result")
    c.check(c.state["events"][-1]["status"] == "stale" and len(c.pending()) == 1, "obsolete result has no new continuation")
    c.check(not c.proof(committed, 2)["authorized"], "old artifact fails new application acceptance criteria")
    c.schedule()
    c.complete("repaired-v2", revision=2)
    c.check(hashlib.sha256(committed.read_bytes()).hexdigest() == prior_hash, "old artifact preserved for comparison")


def cancel_late_result(c):
    c.create()
    c.start()
    c.app.artifact("partial")
    c.wait()
    c.call("cancel", reason="assignment withdrawn")
    c.event()
    c.start("unwanted", expected=False)
    c.check(c.state["status"] == "cancelled" and not c.pending(), "late result cannot revive cancelled assignment")
    c.check(c.state["events"][0]["status"] == "ignored", "late cancelled result retained only as history")


def unsupported_completion(c):
    c.create()
    c.start()
    invalid = c.app.artifact("invalid", valid=False)
    c.finish("complete", expected=False, **c.proof(invalid))
    c.check(c.state["status"] == "running", "failed artifact claim cannot complete work")
    valid = c.app.artifact("valid")
    c.finish("complete", expected=False, **c.proof(valid, reviewer="worker"))
    c.check(c.state["status"] == "running", "unauthorized reviewer cannot accept completion")
    proof = c.proof(valid)
    c.finish("complete", **proof)
    c.finish("complete", attempt="a1", **proof)
    c.finish("continue", attempt="a1", expected=False)
    c.check(c.state["status"] == "completed" and len(c.state["attempts"]) == 1, "accepted completion replays without new work")


def worker_crash(c):
    c.create()
    c.start(kill=True)
    c.call("inspect")
    c.check(c.state["status"] == "running", "durable ownership survives worker SIGKILL")
    c.call("recover", now=4)
    c.check(c.state["active_attempt"] == "a1", "recovery cannot steal unexpired ownership")
    c.call("recover", now=6)
    c.check(c.state["attempts"][0]["status"] == "abandoned", "expired attempt recorded abandoned")
    c.call("recover", now=6)
    c.check(len(c.pending()) == 1, "recovery is idempotent")
    c.schedule(now=6)
    good = c.app.artifact("obsolete-worker-output")
    c.finish("complete", attempt="a1", expected=False, **c.proof(good))
    c.check(c.state["status"] == "running" and c.state["active_attempt"] != "a1", "old worker cannot overwrite replacement")
    c.complete()


def missed_wake(c):
    c.create()
    c.start()
    c.app.artifact("partial", valid=False)
    c.finish("continue", kill=True)
    c.call("inspect")
    c.check(c.state["status"] == "ready" and len(c.pending()) == 1, "continuation intent survives client death before delivery")
    c.schedule()
    c.complete()


def duplicate_wake(c):
    c.create()
    c.start()
    c.finish("continue")
    wake = c.pending()[0]
    identity = "delivery:" + wake["id"]
    c.start(identity, now=10)
    c.check(len(c.pending()) == 1, "start does not silently acknowledge delivery")
    c.start(identity, now=10)
    c.check(len(c.state["attempts"]) == 2, "lost ack and redelivery cannot create another attempt")
    c.call("ack", wake_id=wake["id"])
    c.call("ack", wake_id=wake["id"])
    c.check(not c.pending(), "acknowledgement replay harmless")
    c.complete()


def stale_same_revision(c):
    c.create()
    c.start()
    c.wait(key="same-key")
    c.event("first-result", key="same-key")
    second = c.schedule()
    c.app.artifact("partial-second", valid=False)
    c.wait(attempt=second, key="same-key")
    c.event("delayed-old-result", attempt="a1", key="same-key")
    c.check(c.state["status"] == "waiting" and c.state["events"][-1]["status"] == "stale", "same-revision old result cannot satisfy a new attempt's wait")
    c.event("second-result", attempt=second, key="same-key")
    c.schedule(now=20)
    c.complete()


def bounded_no_progress(c):
    c.create()
    for index in range(3):
        if index == 0:
            c.start()
        else:
            c.schedule(now=index * 10)
        path = c.app.artifact(f"nonprogress-{index}", valid=False)
        c.check(not c.proof(path)["authorized"], "no-progress artifact fails application verification")
        c.finish("continue" if index < 2 else "block", reason="application attempt budget exhausted" if index == 2 else "repair needed")
    last = c.state["attempts"][-1]["id"]
    c.event("late-result", attempt=last)
    c.start("loop", expected=False, now=40)
    c.check(c.state["status"] == "blocked" and len(c.state["attempts"]) == 3 and not c.pending(), "application bound prevents infinite wake loop")


def restart_persistence(c):
    c.create()
    c.start()
    c.app.artifact("pre-restart-partial", valid=False)
    c.wait()
    c.event()
    before = json.loads(json.dumps(c.state))
    if c.manager:
        c.record(control="SIGKILL native Restate server and Python handler; restart same native store")
        c.manager.restart()
    else:
        c.call("inspect", kill=True)
        files = list((c.root / "store").glob("*.sqlite"))
        c.check(len(files) == 1, "one authoritative SQLite lifecycle database")
        with sqlite3.connect(files[0]) as db:
            c.check(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "SQLite store passes integrity check after process death")
        c.record(control="SQLite has no server; killed client and reopened authoritative on-disk store")
    c.call("inspect")
    c.check(c.state == before, "backing-process restart preserves exact lifecycle snapshot")
    c.schedule()
    c.complete()


SCENARIOS = {function.__name__: function for function in (
    normal_continuation, early_event, duplicate_event, revision_after_artifact,
    cancel_late_result, unsupported_completion, worker_crash, missed_wake,
    duplicate_wake, stale_same_revision, bounded_no_progress, restart_persistence,
)}
