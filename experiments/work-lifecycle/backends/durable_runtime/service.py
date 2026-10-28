"""Native Restate entity: the object is the sole lifecycle authority."""
import asyncio
import json

import restate
from hypercorn.asyncio import serve
from hypercorn.config import Config

work = restate.VirtualObject("Assignment")


def reply(state, code="accepted", ok=True):
    return {"ok": ok, "code": code, "state": state}


def intent(state, cause):
    state["wakes"].append({"id": f"wake-{len(state['wakes']) + 1}",
                           "revision": state["revision"], "cause": cause, "status": "pending"})


def retire(state):
    for wake in state["wakes"]:
        if wake["status"] == "pending":
            wake.update(status="delivered", retired=True)
    for event in state["events"]:
        if event["status"] == "buffered":
            event["status"] = "stale"


@work.handler()
async def command(ctx: restate.ObjectContext, request: dict) -> dict:
    state = await ctx.get("assignment")
    op = request.get("op")
    required = {"create": ("domain", "revision"), "inspect": (),
                "start": ("attempt_id", "revision", "now"),
                "finish": ("attempt_id", "revision", "kind", "reason"),
                "event": ("event_id", "key", "revision", "attempt_id", "payload"),
                "revise": ("revision", "reason"), "cancel": ("reason",),
                "recover": ("now",), "ack": ("wake_id",)}
    if op not in required or any(k not in request for k in required.get(op, ())):
        return reply(state, "invalid_request", False)
    if not isinstance(request.get("work_id"), str) or not request["work_id"]:
        return reply(state, "invalid_work_id", False)
    for field in ("revision", "now", "lease_seconds"):
        if field in request and (type(request[field]) is not int or request[field] < (1 if field != "now" else 0)):
            return reply(state, "invalid_" + field, False)
    for field in ("attempt_id", "event_id", "key", "wake_id", "domain", "reason"):
        if field in request and (not isinstance(request[field], str) or not request[field]):
            return reply(state, "invalid_" + field, False)
    if op == "create":
        if state is not None:
            same = state["domain"] == request["domain"] and state["revision"] == request["revision"]
            return reply(state, "replayed" if same else "create_conflict", same)
        if request["revision"] != 1:
            return reply(None, "initial_revision", False)
        state = {"work_id": request["work_id"], "domain": request["domain"], "revision": 1,
                 "status": "ready", "active_attempt": None, "wait_key": None,
                 "waiting_attempt": None, "attempts": [], "events": [], "wakes": [], "history": []}
    elif state is None:
        return reply(None, "not_found", False)
    elif op == "inspect":
        return reply(state, "observed")
    elif op == "start":
        prior = next((a for a in state["attempts"] if a["id"] == request["attempt_id"]), None)
        if prior:
            same = prior["revision"] == request["revision"]
            return reply(state, "replayed" if same else "attempt_conflict", same)
        if state["revision"] != request["revision"]:
            return reply(state, "stale_revision", False)
        if state["status"] != "ready":
            return reply(state, "not_ready", False)
        for event in state["events"]:
            if event["status"] == "buffered":
                event["status"] = "stale"
        state["attempts"].append({"id": request["attempt_id"], "revision": state["revision"],
                                  "status": "running", "lease_until": request["now"] + request.get("lease_seconds", 5)})
        state.update(status="running", active_attempt=request["attempt_id"])
    elif op == "finish":
        attempt = next((a for a in state["attempts"] if a["id"] == request["attempt_id"]), None)
        finish = {k: request[k] for k in ("attempt_id", "revision", "kind", "reason", "wait_key", "authorized", "evidence") if k in request}
        if attempt and "finish" in attempt:
            same = attempt["finish"] == finish
            return reply(state, "replayed" if same else "disposition_conflict", same)
        if state["revision"] != request["revision"]:
            return reply(state, "stale_revision", False)
        if state["status"] != "running" or state["active_attempt"] != request["attempt_id"]:
            return reply(state, "not_owner", False)
        kind = request["kind"]
        if kind not in ("complete", "continue", "wait", "block"):
            return reply(state, "invalid_disposition", False)
        if kind == "complete" and (request.get("authorized") is not True or not request.get("evidence")):
            return reply(state, "completion_not_authorized", False)
        if kind == "wait" and (not isinstance(request.get("wait_key"), str) or not request["wait_key"]):
            return reply(state, "missing_wait_key", False)
        attempt.update(status=kind, finish=finish)
        state["active_attempt"] = None
        if kind == "complete":
            state["status"] = "completed"
        elif kind == "block":
            state["status"] = "blocked"
        elif kind == "continue":
            state["status"] = "ready"
            intent(state, "continue:" + attempt["id"])
        else:
            pending = next((e for e in state["events"] if e["status"] == "buffered" and
                            e["attempt_id"] == attempt["id"] and e["key"] == request["wait_key"]), None)
            if pending:
                pending["status"] = "consumed"
                state["status"] = "ready"
                intent(state, "event:" + pending["id"])
            else:
                state.update(status="waiting", wait_key=request["wait_key"], waiting_attempt=attempt["id"])
    elif op == "event":
        event = {"id": request["event_id"], **{k: request[k] for k in ("key", "revision", "attempt_id", "payload")}}
        existing = next((e for e in state["events"] if e["id"] == event["id"]), None)
        if existing:
            same = all(existing[k] == v for k, v in event.items())
            return reply(state, "replayed" if same else "event_conflict", same)
        source = next((a for a in state["attempts"] if a["id"] == event["attempt_id"]), None)
        if not source or source["revision"] != event["revision"] or event["revision"] > state["revision"]:
            return reply(state, "unknown_source", False)
        if event["revision"] < state["revision"]:
            event["status"] = "stale"
        elif state["status"] in ("cancelled", "completed", "blocked"):
            event["status"] = "ignored"
        elif event["attempt_id"] not in (state["active_attempt"], state["waiting_attempt"]):
            event["status"] = "stale"
        elif state["status"] == "waiting" and event["key"] == state["wait_key"]:
            event["status"] = "consumed"
            state.update(status="ready", wait_key=None, waiting_attempt=None)
            intent(state, "event:" + event["id"])
        else:
            event["status"] = "buffered"
        state["events"].append(event)
    elif op == "revise":
        if request["revision"] == state["revision"]:
            return reply(state, "replayed")
        if request["revision"] != state["revision"] + 1 or state["status"] in ("cancelled", "completed"):
            return reply(state, "revision_conflict", False)
        owner = state["active_attempt"] or state["waiting_attempt"]
        for a in state["attempts"]:
            if a["id"] == owner:
                a["status"] = "superseded"
        retire(state)
        state.update(revision=request["revision"], status="ready", active_attempt=None, wait_key=None, waiting_attempt=None)
        intent(state, "revision:" + str(state["revision"]))
    elif op == "cancel":
        if state["status"] == "completed":
            return reply(state, "already_completed", False)
        if state["status"] == "cancelled":
            return reply(state, "replayed")
        for a in state["attempts"]:
            if a["id"] in (state["active_attempt"], state["waiting_attempt"]):
                a["status"] = "cancelled"
        retire(state)
        state.update(status="cancelled", active_attempt=None, wait_key=None, waiting_attempt=None)
    elif op == "recover":
        owner = next((a for a in state["attempts"] if a["id"] == state["active_attempt"]), None)
        if not owner or request["now"] < owner["lease_until"]:
            return reply(state, "no_expired_owner")
        owner["status"] = "abandoned"
        state.update(status="ready", active_attempt=None)
        intent(state, "recovery:" + owner["id"])
    elif op == "ack":
        wake = next((w for w in state["wakes"] if w["id"] == request["wake_id"]), None)
        if not wake:
            return reply(state, "unknown_wake", False)
        wake["status"] = "delivered"
    state["history"].append({"op": op, "status": state["status"], "revision": state["revision"],
                             "attempt_id": request.get("attempt_id"), "reason": request.get("reason")})
    # A single native state mutation commits the transition and continuation intent together.
    ctx.set("assignment", state)
    return reply(state)


app = restate.app([work])

if __name__ == "__main__":
    config = Config()
    config.bind = ["127.0.0.1:19080"]
    asyncio.run(serve(app, config))
