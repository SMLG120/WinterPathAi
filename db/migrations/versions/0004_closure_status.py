"""CR-ROUTING-7 (accepted): wp.closure.status vocabulary + wp.closure_active_at(closure, t).

Revision ID: 0004_closure_status
Revises: 0003_contract_v1_3_0
Create Date: 2026-11-10

status = publisher lifecycle only: permit_issued | cancelled | completed | unknown. Time-derived
states (active / scheduled / ended) are NOT stored — they go stale between ingests. Consumers
call wp.closure_active_at(c, t), which returns a three-valued boolean:
  true  — permit issued, t inside [valid_from, valid_to], weekday active, t inside the window
  false — explicitly not active at t (outside the date range, inactive weekday, outside window,
          cancelled/completed)
  NULL  — unknown (unknown status, missing/unparseable schedule, overnight window whose
          spill-over semantics the publisher does not document). NULL is never "clear".
Schedule is interpreted in America/Montreal local time. valid_to is inclusive (the publisher
writes 23:59:59 local); an end time of 23:59 is treated as end of day.

Downgrade restores the raw publisher value from attrs.currentstatus (kept verbatim at ingest).
"""

from alembic import op

revision = "0004_closure_status"
down_revision = "0003_contract_v1_3_0"
branch_labels = None
depends_on = None

UPGRADE = r"""
UPDATE wp.closure
   SET status = CASE btrim(status) WHEN 'Permis émis' THEN 'permit_issued' ELSE 'unknown' END
 WHERE status IS NULL
    OR status NOT IN ('permit_issued','cancelled','completed','unknown');

ALTER TABLE wp.closure
  ADD CONSTRAINT closure_status_check
  CHECK (status IN ('permit_issued','cancelled','completed','unknown'));

CREATE FUNCTION wp.closure_active_at(c wp.closure, t timestamptz)
RETURNS boolean
LANGUAGE plpgsql STABLE PARALLEL SAFE
AS $fn$
DECLARE
  lt    timestamp := t AT TIME ZONE 'America/Montreal';
  dname text := (ARRAY['mon','tue','wed','thu','fri','sat','sun'])[extract(isodow FROM lt)::int];
  d     jsonb;
  s     text;
  e     text;
  hhmm  constant text := '^[0-2][0-9]:[0-5][0-9](:[0-5][0-9])?$';
BEGIN
  IF t IS NULL THEN RETURN NULL; END IF;
  IF c.status IN ('cancelled','completed') THEN RETURN false; END IF;
  IF c.status IS DISTINCT FROM 'permit_issued' THEN RETURN NULL; END IF;
  IF c.valid_from IS NULL THEN RETURN NULL; END IF;
  IF t < c.valid_from OR (c.valid_to IS NOT NULL AND t > c.valid_to) THEN RETURN false; END IF;

  d := c.attrs -> 'weekly_schedule' -> dname;
  IF d IS NULL OR jsonb_typeof(d -> 'active') IS DISTINCT FROM 'boolean' THEN RETURN NULL; END IF;
  IF NOT (d ->> 'active')::boolean THEN RETURN false; END IF;
  IF jsonb_typeof(d -> 'all_day') IS DISTINCT FROM 'boolean' THEN RETURN NULL; END IF;
  IF (d ->> 'all_day')::boolean THEN RETURN true; END IF;

  s := d ->> 'start';
  e := d ->> 'end';
  IF s IS NULL OR e IS NULL OR s !~ hhmm OR e !~ hhmm THEN RETURN NULL; END IF;
  IF left(e, 5) = '23:59' THEN e := '24:00'; END IF;
  IF e::time <= s::time THEN RETURN NULL; END IF;  -- overnight window: undocumented → unknown
  RETURN lt::time >= s::time AND lt::time < e::time;
END
$fn$;

COMMENT ON FUNCTION wp.closure_active_at(wp.closure, timestamptz) IS
  'CR-ROUTING-7: true/false/NULL(unknown) whether the permit is active at t (America/Montreal '
  'schedule). Activity only — combine with blocks_passage. NULL must never be treated as clear.';

REVOKE ALL ON FUNCTION wp.closure_active_at(wp.closure, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION wp.closure_active_at(wp.closure, timestamptz)
  TO wp_reader, wp_writer, wp_migrator;
"""

DOWNGRADE = r"""
DROP FUNCTION IF EXISTS wp.closure_active_at(wp.closure, timestamptz);
ALTER TABLE wp.closure DROP CONSTRAINT IF EXISTS closure_status_check;
UPDATE wp.closure SET status = attrs ->> 'currentstatus' WHERE attrs ? 'currentstatus';
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
