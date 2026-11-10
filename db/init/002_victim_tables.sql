-- Level 1 "victim world": logs, metrics and deploys the agents will investigate.

CREATE TABLE IF NOT EXISTS log_events (
    id      BIGSERIAL PRIMARY KEY,
    service TEXT        NOT NULL,
    level   TEXT        NOT NULL,
    message TEXT        NOT NULL,
    ts      TIMESTAMPTZ NOT NULL,
    fields  JSONB       NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_log_service_ts ON log_events (service, ts DESC);
CREATE INDEX IF NOT EXISTS idx_log_level_ts   ON log_events (level, ts DESC);
CREATE INDEX IF NOT EXISTS idx_log_fts        ON log_events USING GIN (to_tsvector('english', message));

CREATE TABLE IF NOT EXISTS metric_points (
    id      BIGSERIAL PRIMARY KEY,
    service TEXT             NOT NULL,
    name    TEXT             NOT NULL,
    value   DOUBLE PRECISION NOT NULL,
    ts      TIMESTAMPTZ      NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metric_lookup ON metric_points (service, name, ts DESC);

CREATE TABLE IF NOT EXISTS deploy_events (
    id      BIGSERIAL PRIMARY KEY,
    sha     TEXT        NOT NULL,
    service TEXT        NOT NULL,
    author  TEXT        NOT NULL,
    message TEXT        NOT NULL,
    ts      TIMESTAMPTZ NOT NULL,
    files   JSONB       NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_deploy_service_ts ON deploy_events (service, ts DESC);

-- The answer key. Agents must never read this table; only the evaluation runner will.
CREATE TABLE IF NOT EXISTS scenario_runs (
    id         BIGSERIAL PRIMARY KEY,
    scenario   TEXT        NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expected   JSONB       NOT NULL
);
