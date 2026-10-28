"""Test-transport adapter for the WorkStore public methods."""
from .core import Conflict, WorkStore

METHODS = {
    "create": ("create", ("domain", "revision"), ()),
    "inspect": ("inspect", (), ()),
    "start": ("claim", ("attempt_id", "revision", "now"), ("lease_seconds",)),
    "finish": ("accept", ("attempt_id", "revision", "kind", "reason"), ("wait_key", "authorized", "evidence")),
    "event": ("notify", ("event_id", "key", "revision", "attempt_id", "payload"), ()),
    "revise": ("revise", ("revision", "reason"), ()),
    "cancel": ("cancel", ("reason",), ()),
    "recover": ("recover", ("now",), ()),
    "ack": ("acknowledge", ("wake_id",), ()),
}


class Backend:
    def __init__(self, root):
        self.store = WorkStore(root / "goalflow.sqlite")

    def command(self, q):
        try:
            if q.get("op") not in METHODS:
                raise Conflict("invalid_request")
            name, required, optional = METHODS[q["op"]]
            if any(f not in q for f in ("work_id", *required)):
                raise Conflict("invalid_request")
            for f in ("work_id", "domain", "attempt_id", "event_id", "key", "wake_id", "reason"):
                if f in q and (not isinstance(q[f], str) or not q[f]):
                    raise Conflict("invalid_" + f)
            for f in ("revision", "now", "lease_seconds"):
                if f in q and (type(q[f]) is not int or q[f] < (0 if f == "now" else 1)):
                    raise Conflict("invalid_" + f)
            fields = {f: q[f] for f in (*required, *optional) if f in q}
            return getattr(self.store, name)(q["work_id"], **fields)
        except Conflict as error:
            try:
                current = self.store.inspect(q.get("work_id"))["state"]
            except Conflict:
                current = None
            return {"ok": False, "code": str(error), "state": current}
