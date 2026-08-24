-- Existing FlowPilot PostgreSQL databases are initialized before this change.
-- Apply once after upgrading the application; init.sql covers newly created DBs.

ALTER TABLE executions DROP CONSTRAINT IF EXISTS executions_status_check;
ALTER TABLE executions
    ADD CONSTRAINT executions_status_check
    CHECK (status IN ('pending', 'running', 'unknown', 'succeeded', 'failed', 'escalated'));

ALTER TABLE executions
    ADD COLUMN IF NOT EXISTS reconcile_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS next_reconcile_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_reconciled_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_executions_reconcile_due
    ON executions(status, next_reconcile_at);
