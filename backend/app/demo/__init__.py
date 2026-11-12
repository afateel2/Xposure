"""
Live demo pipeline: a one-click, repeatable, honest run of the whole agent.

The story the demo tells: a company that is compliant with ECC-1:2018 presses
"Scan now", the agent finds the newly published ECC-2:2024, and the real
pipeline (ingest, align, classify, impact, prioritize, policy) runs with
visible progress until the changes are ready for a human to review. Then
"reset" restores the starting point so the run can be repeated.

Modules:
  constants.py   baseline identity (nca / ecc / 1-2018), event names, stages
  mirror.py      the local mirror of the regulator portal (demo stand-in)
  backup.py      the one-time pg_dump before the first destructive reset
  baseline.py    reset_to_baseline(): the demo reset
  tracker.py     in-process run state, mirrored to audit_log, restart safe
  runner.py      the background scan: portal check, fetch, then the real graph
  status.py      GET /demo/status
  prepare.py     `python -m app.demo.prepare`: warm the LLM and embedding caches

Nothing here fakes a result. The portal is a local folder and says so; cached
model answers are real earlier answers and the run says how many there were.
"""
