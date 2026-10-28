# Architecture and supported boundaries

`goalflow_world/store.py` provides deterministic fictional participants, documents, messages, tasks, business time and events. Visible world state and future-event control are separate SQLite databases. Fixtures describe Cedar Studio and Harbor Learning; people, commercial details and `.test` addresses are synthetic.

`tools/world_server.py` exposes nine run-bound tools. `goalflow_baseline/bridge.py` enforces the capability set; the model receives neither evaluator access nor arbitrary filesystem tools. The operator and host still have filesystem access: this is not an OS security sandbox.

`runner.py` maintains the sequential model/tool loop. `state.py` stores checkpoints, request records and conservative integer-micro-dollar reservations. An uncertain model request stops with its reservation retained. An uncertain tool reply retains the operation and stable arguments for local idempotent replay. No generic guarantee about remote side effects is made.

`workflow.py` saves immutable brief revisions, exact read-back receipts and agent outcome claims. `evaluator.py` checks state, references, authority, tasks and historical effects separately from claims. Semantic review is bound to artifact/state hashes but relies on trusted review metadata; it does not authenticate a human reviewer.

`evidence.py` and `freeze.py` capture and hash sources, configuration, state and process boundaries. Cross-database consistency has explicit limits; hashes detect changes but are not tamper-proof storage. The release source differs from the original study freeze, and generates new freeze identities.

The lifecycle experiment has separate implementations: independently implemented SQLite WorkStore; custom Restate service/client code on the external runtime; and a custom persistence/transport adapter executing unmodified Paperclip arbiter code. Work identity survives finite attempts. Transactions guard ownership, revision, event consumption and continuation intents. Application policy supplies attempt ceilings and completion evidence. Logical leases, aggregate storage and fixture scheduling are deliberate prototype boundaries; completed work cannot be revised in place.
