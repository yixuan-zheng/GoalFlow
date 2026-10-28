"""Small persistent work/attempt/disposition component, with application policy outside.

SQLite serializes mutations. One aggregate row commits ownership, accepted
disposition, inbox and continuation intents atomically. This bounded prototype
does not provide a distributed scheduler or external-effect guarantees.
"""
from contextlib import contextmanager
from functools import wraps
import json
import sqlite3


class Conflict(Exception):
    """The requested transition is not admissible against the stored work."""


def mutation(function):
    @wraps(function)
    def apply(self, work_id, **arguments):
        with self.transaction() as db:
            state = self.load(db, work_id)
            code = function(self, state, **arguments) or "accepted"
            if code != "replayed":
                state["history"].append({"op": function.__name__, "revision": state["revision"],
                                         "status": state["status"], "reason": arguments.get("reason"),
                                         "attempt_id": arguments.get("attempt_id")})
                self.save(db, state)
            return {"ok": True, "code": code, "state": state}
    return apply


class WorkStore:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=20) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS work (id TEXT PRIMARY KEY, state TEXT NOT NULL)")

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=20, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    @staticmethod
    def load(db, work_id):
        row = db.execute("SELECT state FROM work WHERE id=?", (work_id,)).fetchone()
        if row is None:
            raise Conflict("not_found")
        return json.loads(row[0])

    @staticmethod
    def save(db, state):
        db.execute("INSERT INTO work VALUES (?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state",
                   (state["work_id"], json.dumps(state, sort_keys=True)))

    def inspect(self, work_id):
        with self.transaction() as db:
            return {"ok": True, "code": "observed", "state": self.load(db, work_id)}

    def create(self, work_id, domain, revision):
        with self.transaction() as db:
            row = db.execute("SELECT state FROM work WHERE id=?", (work_id,)).fetchone()
            if row:
                state = json.loads(row[0])
                if (state["domain"], state["revision"]) != (domain, revision):
                    raise Conflict("create_conflict")
                return {"ok": True, "code": "replayed", "state": state}
            if revision != 1:
                raise Conflict("initial_revision")
            state = {"work_id": work_id, "domain": domain, "revision": revision, "status": "ready",
                     "active_attempt": None, "wait_key": None, "waiting_attempt": None,
                     "attempts": [], "events": [], "wakes": [], "history": [{"op": "create", "revision": revision, "status": "ready"}]}
            self.save(db, state)
            return {"ok": True, "code": "accepted", "state": state}

    @staticmethod
    def attempt(state, attempt_id):
        return next((a for a in state["attempts"] if a["id"] == attempt_id), None)

    @staticmethod
    def wake(state, cause):
        state["wakes"].append({"id": "continuation-" + str(len(state["wakes"]) + 1),
                               "cause": cause, "revision": state["revision"], "status": "pending"})

    @staticmethod
    def invalidate(state):
        for intent in state["wakes"]:
            if intent["status"] == "pending":
                intent.update(status="delivered", retired=True)
        for event in state["events"]:
            if event["status"] == "buffered":
                event["status"] = "stale"
        for attempt in state["attempts"]:
            if attempt["id"] in (state["active_attempt"], state["waiting_attempt"]):
                attempt["status"] = "superseded"
        state.update(active_attempt=None, waiting_attempt=None, wait_key=None)

    @mutation
    def claim(self, state, attempt_id, revision, now, lease_seconds=5):
        existing = self.attempt(state, attempt_id)
        if existing:
            if existing["revision"] != revision:
                raise Conflict("attempt_conflict")
            return "replayed"
        if revision != state["revision"]:
            raise Conflict("stale_revision")
        if state["status"] != "ready":
            raise Conflict("not_ready")
        for event in state["events"]:
            if event["status"] == "buffered":
                event["status"] = "stale"
        state["attempts"].append({"id": attempt_id, "revision": revision, "status": "running", "lease_until": now + lease_seconds})
        state.update(status="running", active_attempt=attempt_id)

    @mutation
    def accept(self, state, attempt_id, revision, kind, reason, wait_key=None, authorized=False, evidence=None):
        attempt = self.attempt(state, attempt_id)
        proposal = {"attempt_id": attempt_id, "revision": revision, "kind": kind, "reason": reason,
                    "wait_key": wait_key, "authorized": authorized, "evidence": evidence}
        if attempt and "finish" in attempt:
            if attempt["finish"] != proposal:
                raise Conflict("disposition_conflict")
            return "replayed"
        if revision != state["revision"]:
            raise Conflict("stale_revision")
        if state["status"] != "running" or state["active_attempt"] != attempt_id:
            raise Conflict("not_owner")
        if kind not in ("complete", "continue", "wait", "block"):
            raise Conflict("invalid_disposition")
        if kind == "complete" and (authorized is not True or not evidence):
            raise Conflict("completion_not_authorized")
        if kind == "wait" and (not isinstance(wait_key, str) or not wait_key):
            raise Conflict("missing_wait_key")
        attempt.update(status=kind, finish=proposal)
        state["active_attempt"] = None
        state["status"] = {"complete": "completed", "continue": "ready", "wait": "waiting", "block": "blocked"}[kind]
        if kind == "continue":
            self.wake(state, "continue:" + attempt_id)
        elif kind == "wait":
            buffered = next((e for e in state["events"] if e["status"] == "buffered" and
                             e["attempt_id"] == attempt_id and e["key"] == wait_key), None)
            if buffered:
                buffered["status"] = "consumed"
                state["status"] = "ready"
                self.wake(state, "event:" + buffered["id"])
            else:
                state.update(wait_key=wait_key, waiting_attempt=attempt_id)

    @mutation
    def notify(self, state, event_id, key, revision, attempt_id, payload):
        incoming = {"id": event_id, "key": key, "revision": revision, "attempt_id": attempt_id, "payload": payload}
        previous = next((e for e in state["events"] if e["id"] == event_id), None)
        if previous:
            if any(previous[k] != value for k, value in incoming.items()):
                raise Conflict("event_conflict")
            return "replayed"
        source = self.attempt(state, attempt_id)
        if source is None or source["revision"] != revision or revision > state["revision"]:
            raise Conflict("unknown_source")
        if revision < state["revision"]:
            outcome = "stale"
        elif state["status"] in ("completed", "cancelled", "blocked"):
            outcome = "ignored"
        elif attempt_id not in (state["active_attempt"], state["waiting_attempt"]):
            outcome = "stale"
        elif state["status"] == "waiting" and key == state["wait_key"]:
            outcome = "consumed"
            state.update(status="ready", wait_key=None, waiting_attempt=None)
            self.wake(state, "event:" + event_id)
        else:
            outcome = "buffered"
        state["events"].append({**incoming, "status": outcome})

    @mutation
    def revise(self, state, revision, reason):
        if revision == state["revision"]:
            return "replayed"
        if revision != state["revision"] + 1 or state["status"] in ("completed", "cancelled"):
            raise Conflict("revision_conflict")
        self.invalidate(state)
        state.update(revision=revision, status="ready")
        self.wake(state, "revision:" + str(revision))

    @mutation
    def cancel(self, state, reason):
        if state["status"] == "completed":
            raise Conflict("already_completed")
        if state["status"] == "cancelled":
            return "replayed"
        owner = state["active_attempt"] or state["waiting_attempt"]
        self.invalidate(state)
        if owner:
            self.attempt(state, owner)["status"] = "cancelled"
        state["status"] = "cancelled"

    @mutation
    def recover(self, state, now):
        attempt = self.attempt(state, state["active_attempt"])
        if attempt is None or now < attempt["lease_until"]:
            return "no_expired_owner"
        attempt["status"] = "abandoned"
        state.update(status="ready", active_attempt=None)
        self.wake(state, "recovery:" + attempt["id"])

    @mutation
    def acknowledge(self, state, wake_id):
        intent = next((w for w in state["wakes"] if w["id"] == wake_id), None)
        if intent is None:
            raise Conflict("unknown_wake")
        intent["status"] = "delivered"
