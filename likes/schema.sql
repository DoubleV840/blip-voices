-- One row per like: which voice, who (a salted hash), when (ms).
CREATE TABLE IF NOT EXISTS likes (
  voice TEXT NOT NULL,
  voter TEXT NOT NULL,
  at INTEGER NOT NULL,
  PRIMARY KEY (voice, voter)
);
CREATE INDEX IF NOT EXISTS likes_by_voter ON likes (voter, at);

-- One row per voice shared from the site: its fields; its sound (the site's
-- .wav, base64) until the workflow is done with it; who shared it (a salted
-- hash) and when (ms); how far it is (queued, checking, publishing, live,
-- refused, failed, removed) and why; the version it went live as; and the
-- hash of the key that lets its sharer remove it.
CREATE TABLE IF NOT EXISTS submissions (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  theme TEXT NOT NULL,
  description TEXT NOT NULL,
  author TEXT NOT NULL,
  wav TEXT,
  sharer TEXT NOT NULL,
  at INTEGER NOT NULL,
  status TEXT NOT NULL,
  reason TEXT,
  version TEXT,
  key TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS submissions_by_time ON submissions (at);
CREATE INDEX IF NOT EXISTS submissions_by_name ON submissions (name, status);
