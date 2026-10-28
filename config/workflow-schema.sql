CREATE TABLE briefs (
    id TEXT NOT NULL, revision INTEGER NOT NULL, data TEXT NOT NULL,
    markdown TEXT NOT NULL, sha256 TEXT NOT NULL, published_at TEXT NOT NULL,
    state_snapshot TEXT NOT NULL, PRIMARY KEY(id, revision)
);
CREATE TABLE brief_reads (
    id TEXT NOT NULL, revision INTEGER NOT NULL, sha256 TEXT NOT NULL,
    audit_seq INTEGER NOT NULL, PRIMARY KEY(id, revision, sha256)
);
CREATE TABLE submissions (seq INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL);
