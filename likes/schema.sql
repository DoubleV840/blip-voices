-- One row per like: which voice, who (a salted hash), when (ms).
CREATE TABLE IF NOT EXISTS likes (
  voice TEXT NOT NULL,
  voter TEXT NOT NULL,
  at INTEGER NOT NULL,
  PRIMARY KEY (voice, voter)
);
CREATE INDEX IF NOT EXISTS likes_by_voter ON likes (voter, at);
