CREATE TABLE IF NOT EXISTS crm_staff (
  id BIGINT PRIMARY KEY,
  telegram_id BIGINT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('operator','admin','owner')),
  active BOOLEAN NOT NULL DEFAULT TRUE
);
ALTER TABLE crm_staff ALTER COLUMN telegram_id DROP NOT NULL;
ALTER TABLE crm_staff ADD COLUMN IF NOT EXISTS login_name TEXT UNIQUE;
ALTER TABLE crm_staff ADD COLUMN IF NOT EXISTS password_hash TEXT;
CREATE SEQUENCE IF NOT EXISTS crm_seller_seq START 1000000000;
CREATE TABLE IF NOT EXISTS crm_login_sessions (
  token_hash TEXT PRIMARY KEY,
  staff_id BIGINT NOT NULL REFERENCES crm_staff(id) ON DELETE CASCADE,
  csrf_token TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS crm_leads (
  id BIGINT PRIMARY KEY,
  telegram_user_id BIGINT,
  username TEXT,
  request_type TEXT NOT NULL,
  name TEXT NOT NULL,
  phone TEXT NOT NULL,
  course_id BIGINT,
  course_name TEXT,
  branch_id BIGINT,
  branch_name TEXT,
  source TEXT NOT NULL,
  campaign_code TEXT,
  status TEXT NOT NULL DEFAULT 'Yangi lead',
  assignee_id BIGINT REFERENCES crm_staff(id) ON DELETE SET NULL,
  preferred_contact_time TEXT,
  note TEXT,
  next_action_at TIMESTAMPTZ,
  meeting_at TIMESTAMPTZ,
  meeting_format TEXT,
  lost_reason TEXT,
  first_contact_at TIMESTAMPTZ,
  closed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  bot_updated_at TIMESTAMPTZ NOT NULL,
  anonymized BOOLEAN NOT NULL DEFAULT FALSE,
  merged_into_id BIGINT
);
CREATE INDEX IF NOT EXISTS crm_leads_assignee_status ON crm_leads(assignee_id,status);
CREATE INDEX IF NOT EXISTS crm_leads_next_action ON crm_leads(next_action_at);
CREATE INDEX IF NOT EXISTS crm_leads_created ON crm_leads(created_at DESC);
CREATE TABLE IF NOT EXISTS crm_events (
  id BIGSERIAL PRIMARY KEY,
  lead_id BIGINT NOT NULL REFERENCES crm_leads(id) ON DELETE CASCADE,
  actor_id BIGINT REFERENCES crm_staff(id) ON DELETE SET NULL,
  kind TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT,
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS crm_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS crm_tasks (
  id BIGSERIAL PRIMARY KEY,
  title TEXT NOT NULL,
  details TEXT NOT NULL DEFAULT '',
  assignee_id BIGINT NOT NULL REFERENCES crm_staff(id),
  created_by BIGINT REFERENCES crm_staff(id),
  lead_id BIGINT REFERENCES crm_leads(id) ON DELETE SET NULL,
  due_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','done')),
  source TEXT NOT NULL DEFAULT 'web',
  source_request_id BIGINT UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS crm_tasks_assignee_status ON crm_tasks(assignee_id,status,due_at);
CREATE TABLE IF NOT EXISTS crm_task_events (
  id BIGSERIAL PRIMARY KEY,
  task_id BIGINT NOT NULL REFERENCES crm_tasks(id) ON DELETE CASCADE,
  actor_id BIGINT REFERENCES crm_staff(id),
  kind TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
