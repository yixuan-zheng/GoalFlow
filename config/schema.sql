PRAGMA foreign_keys = ON;
CREATE TABLE people (
  id TEXT PRIMARY KEY, role TEXT NOT NULL, authority_json TEXT NOT NULL
);
CREATE TABLE documents (
  id TEXT NOT NULL, version INTEGER NOT NULL, body TEXT NOT NULL,
  status TEXT NOT NULL, PRIMARY KEY(id, version)
);
CREATE TABLE messages (
  id TEXT PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL,
  thread_id TEXT NOT NULL, body TEXT NOT NULL,
  occurred_at TEXT NOT NULL, delivered_at TEXT NOT NULL
);
CREATE TABLE tasks (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, owner TEXT NOT NULL,
  status TEXT NOT NULL, source_json TEXT NOT NULL
);
CREATE TABLE approvals (
  id TEXT PRIMARY KEY, actor TEXT NOT NULL, artifact TEXT NOT NULL,
  version INTEGER NOT NULL, scope_hash TEXT NOT NULL, decision TEXT NOT NULL
);
CREATE TABLE events (
  id TEXT PRIMARY KEY, trigger_json TEXT NOT NULL,
  payload_json TEXT NOT NULL, processed_at TEXT
);
CREATE TABLE effects (
  request_id TEXT PRIMARY KEY, tool TEXT NOT NULL,
  args_hash TEXT NOT NULL, result_json TEXT, state TEXT NOT NULL
);
CREATE TABLE audit (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL, occurred_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
