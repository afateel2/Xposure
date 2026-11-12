"""
Visibility layer: read-only helpers behind GET /overview, /activity, /audit,
/tasks, /agent/state, /changes/{id}/timeline and /changes/new-count.

Everything here only SELECTs. It never writes a row (audit_log is
append-only, and the demo/pipeline agents own every write). Human-readable
text is generated from audit_log rows and real table rows only: a sentence
is never invented for something that did not happen.

Modules:
  timeutil       naive-UTC in the database, timezone-aware UTC on the wire
  labels         bilingual vocabulary (action types, statuses, bands) and
                 Arabic counting helpers
  window         "since the last demo_reset" window
  priority_index bulk priority band per change (same maths as /changes)
  events         audit event catalogue: kind, severity, icon, EN/AR text,
                 plus the collapse rules for the activity feed
  agent_state    idle | scanning | awaiting_review | failed derived from audit
  planned        regulators that are documented as planned future work
"""
