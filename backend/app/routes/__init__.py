"""
M7 API routes. One module per resource, each exporting an APIRouter that
main.py mounts directly (plain paths, no /api prefix here — the Next.js
frontend's own /api/* route handlers do the proxying and prefixing, same
pattern as /health: see frontend/app/api/health/route.ts).

Read routes (changes, sources, settings) query the database directly and
return Pydantic response models (schemas.py, mirrored by hand into
frontend/lib/types.ts per the takeoff prompt's contract-mirroring rule).
The one write path (actions.py's approve/dismiss) does not resume a
LangGraph thread — see agent/graph.py's human_review_node docstring:
"The global inbox is M7's UI, which approves/dismisses through the API
rather than by resuming a graph thread." It writes Action.status and an
AuditLog row directly, in the same spirit as human_review_node's own
resume path but through the API instead of the CLI.
"""
