"""Pinned Paperclip arbiter + explicitly custom SQLite lifecycle materializer.

This is an extraction baseline, not Paperclip's native committer or recovery.
"""
import json
from pathlib import Path
import sqlite3
import subprocess

HERE = Path(__file__).resolve().parent


class Invalid(Exception):
    pass


class Backend:
    def __init__(self, root):
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "paperclip-extraction.sqlite"
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS issues (id TEXT PRIMARY KEY, document TEXT NOT NULL)")

    def command(self, request):
        with sqlite3.connect(self.path, timeout=20) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT document FROM issues WHERE id=?", (request.get("work_id"),)).fetchone()
            state = json.loads(row[0]) if row else None
            original = json.loads(row[0]) if row else None
            try:
                self.validate(request)
                if state is None and request["op"] != "create":
                    raise Invalid("not_found")
                state, code = getattr(self, request["op"])(state, request)
            except Invalid as error:
                return {"ok": False, "code": str(error), "state": original}
            if request["op"] != "inspect" and code != "replayed":
                state["history"].append({"op": request["op"], "status": state["status"],
                                         "revision": state["revision"], "attempt_id": request.get("attempt_id"),
                                         "reason": request.get("reason")})
                db.execute("INSERT INTO issues VALUES (?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document",
                           (state["work_id"], json.dumps(state, sort_keys=True)))
            return {"ok": True, "code": code, "state": state}

    @staticmethod
    def validate(q):
        fields = {"create": ("domain", "revision"), "inspect": (),
                  "start": ("attempt_id", "revision", "now"),
                  "finish": ("attempt_id", "revision", "kind", "reason"),
                  "event": ("event_id", "key", "revision", "attempt_id", "payload"),
                  "revise": ("revision", "reason"), "cancel": ("reason",),
                  "recover": ("now",), "ack": ("wake_id",)}
        if q.get("op") not in fields or any(f not in q for f in fields.get(q.get("op"), ())):
            raise Invalid("invalid_request")
        for f in ("work_id", "domain", "attempt_id", "event_id", "key", "wake_id", "reason"):
            if f == "work_id" or f in q:
                if not isinstance(q.get(f), str) or not q[f]:
                    raise Invalid("invalid_" + f)
        for f in ("revision", "now", "lease_seconds"):
            if f in q and (type(q[f]) is not int or q[f] < (0 if f == "now" else 1)):
                raise Invalid("invalid_" + f)

    def create(self, state, q):
        if state:
            if (state["domain"], state["revision"]) != (q["domain"], q["revision"]):
                raise Invalid("create_conflict")
            return state, "replayed"
        if q["revision"] != 1:
            raise Invalid("initial_revision")
        return {"work_id": q["work_id"], "domain": q["domain"], "revision": 1,
                "status": "ready", "native_status": "todo", "active_attempt": None,
                "wait_key": None, "waiting_attempt": None, "attempts": [], "events": [],
                "wakes": [], "history": [], "native_decisions": []}, "accepted"

    def inspect(self, state, q):
        return state, "observed"

    @staticmethod
    def find(items, identity):
        return next((item for item in items if item["id"] == identity), None)

    @staticmethod
    def wake(state, cause):
        state["wakes"].append({"id": f"effect-{len(state['wakes']) + 1}",
                               "revision": state["revision"], "cause": cause, "status": "pending"})

    def start(self, state, q):
        previous = self.find(state["attempts"], q["attempt_id"])
        if previous:
            if previous["revision"] != q["revision"]:
                raise Invalid("attempt_conflict")
            return state, "replayed"
        if q["revision"] != state["revision"]:
            raise Invalid("stale_revision")
        if state["status"] != "ready":
            raise Invalid("not_ready")
        for event in state["events"]:
            if event["status"] == "buffered":
                event["status"] = "stale"
        state["attempts"].append({"id": q["attempt_id"], "revision": q["revision"],
                                  "status": "running", "lease_until": q["now"] + q.get("lease_seconds", 5)})
        state.update(status="running", native_status="in_progress", active_attempt=q["attempt_id"])
        return state, "accepted"

    def finish(self, state, q):
        attempt = self.find(state["attempts"], q["attempt_id"])
        proposal = {f: q[f] for f in ("attempt_id", "revision", "kind", "reason", "wait_key", "authorized", "evidence") if f in q}
        if attempt and "finish" in attempt:
            if attempt["finish"] != proposal:
                raise Invalid("disposition_conflict")
            return state, "replayed"
        if q["revision"] != state["revision"]:
            raise Invalid("stale_revision")
        if state["status"] != "running" or state["active_attempt"] != q["attempt_id"]:
            raise Invalid("not_owner")
        if q["kind"] not in ("complete", "continue", "wait", "block"):
            raise Invalid("invalid_disposition")
        if q["kind"] == "wait" and (not isinstance(q.get("wait_key"), str) or not q["wait_key"]):
            raise Invalid("missing_wait_key")
        process = subprocess.run(["node", "--no-warnings", "--experimental-strip-types", "--experimental-loader",
                                  str(HERE / "resolve-ts.mjs"), str(HERE / "arbiter-runner.mjs")],
                                 input=json.dumps(q), capture_output=True, text=True, timeout=15)
        if process.returncode:
            raise RuntimeError("Native arbiter failed: " + process.stderr)
        decision = json.loads(process.stdout)
        expected = {"complete": "done", "continue": "in_progress", "wait": "in_review", "block": "blocked"}
        if decision["toStatus"] != expected[q["kind"]] or decision["statusAction"] == "preserve":
            raise Invalid("arbiter:" + str(decision["reasonCode"]))
        state["native_decisions"].append(decision)
        state["native_status"] = decision["toStatus"]
        attempt.update(status=q["kind"], finish=proposal)
        state["active_attempt"] = None
        if q["kind"] == "complete":
            state["status"] = "completed"
        elif q["kind"] == "block":
            state["status"] = "blocked"
        elif q["kind"] == "continue":
            effects = [e for e in decision["effects"] if e["kind"] == "enqueue_continuation"]
            if not effects:
                raise Invalid("native_continuation_missing")
            state["status"] = "ready"
            self.wake(state, effects[0]["idempotencyKey"])
        else:
            result = next((e for e in state["events"] if e["status"] == "buffered" and
                           e["attempt_id"] == q["attempt_id"] and e["key"] == q["wait_key"]), None)
            if result:
                result["status"] = "consumed"
                state.update(status="ready", native_status="in_progress")
                self.wake(state, "resolved-stage:" + result["id"])
            else:
                state.update(status="waiting", wait_key=q["wait_key"], waiting_attempt=q["attempt_id"])
        return state, "accepted"

    def event(self, state, q):
        value = {"id": q["event_id"], **{f: q[f] for f in ("key", "revision", "attempt_id", "payload")}}
        existing = self.find(state["events"], q["event_id"])
        if existing:
            if any(existing[f] != v for f, v in value.items()):
                raise Invalid("event_conflict")
            return state, "replayed"
        source = self.find(state["attempts"], q["attempt_id"])
        if not source or source["revision"] != q["revision"] or q["revision"] > state["revision"]:
            raise Invalid("unknown_source")
        value["status"] = "buffered"
        if q["revision"] < state["revision"]:
            value["status"] = "stale"
        elif state["status"] in ("cancelled", "completed", "blocked"):
            value["status"] = "ignored"
        elif q["attempt_id"] not in (state["active_attempt"], state["waiting_attempt"]):
            value["status"] = "stale"
        elif state["status"] == "waiting" and q["key"] == state["wait_key"]:
            value["status"] = "consumed"
            state.update(status="ready", native_status="in_progress", wait_key=None, waiting_attempt=None)
            self.wake(state, "resolved-stage:" + q["event_id"])
        state["events"].append(value)
        return state, "accepted"

    @staticmethod
    def retire(state):
        for w in state["wakes"]:
            if w["status"] == "pending":
                w.update(status="delivered", retired=True)
        for e in state["events"]:
            if e["status"] == "buffered":
                e["status"] = "stale"

    def revise(self, state, q):
        if state["revision"] == q["revision"]:
            return state, "replayed"
        if q["revision"] != state["revision"] + 1 or state["status"] in ("completed", "cancelled"):
            raise Invalid("revision_conflict")
        for a in state["attempts"]:
            if a["id"] in (state["active_attempt"], state["waiting_attempt"]):
                a["status"] = "superseded"
        self.retire(state)
        state.update(revision=q["revision"], status="ready", native_status="todo", active_attempt=None,
                     wait_key=None, waiting_attempt=None)
        self.wake(state, "contract-revision:" + str(q["revision"]))
        return state, "accepted"

    def cancel(self, state, q):
        if state["status"] == "completed":
            raise Invalid("already_completed")
        if state["status"] == "cancelled":
            return state, "replayed"
        for a in state["attempts"]:
            if a["id"] in (state["active_attempt"], state["waiting_attempt"]):
                a["status"] = "cancelled"
        self.retire(state)
        state.update(status="cancelled", native_status="cancelled", active_attempt=None, wait_key=None, waiting_attempt=None)
        return state, "accepted"

    def recover(self, state, q):
        owner = self.find(state["attempts"], state["active_attempt"])
        if not owner or q["now"] < owner["lease_until"]:
            return state, "no_expired_owner"
        owner["status"] = "abandoned"
        state.update(status="ready", active_attempt=None)
        self.wake(state, "recovery:" + owner["id"])
        return state, "accepted"

    def ack(self, state, q):
        effect = self.find(state["wakes"], q["wake_id"])
        if not effect:
            raise Invalid("unknown_wake")
        effect["status"] = "delivered"
        return state, "accepted"
