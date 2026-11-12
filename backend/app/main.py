from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import llm, retriever
from .config import settings
from .db.session import db_reachable
from .routes import (
    actions,
    agent as agent_routes,
    agent_console,
    auth as auth_routes,
    changes,
    company as company_routes,
    exports,
    overview as overview_routes,
    settings as settings_routes,
    sources,
    trends,
    webhooks as webhooks_routes,
)

app = FastAPI(title="Xposure API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3010", "http://127.0.0.1:3010",
    ],
    allow_credentials=True,  # session cookie (app/auth.py), for any direct browser call
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)

app.include_router(auth_routes.router)

# Visibility layer (overview, activity, audit, tasks, agent state, timeline).
# Must come BEFORE changes.router so /changes/new-count is not captured by
# /changes/{change_id}.
app.include_router(overview_routes.router)
app.include_router(changes.router)
app.include_router(actions.router)
app.include_router(sources.router)
app.include_router(settings_routes.router)
app.include_router(webhooks_routes.router)
app.include_router(exports.router)
app.include_router(agent_routes.router)
app.include_router(trends.router)
app.include_router(agent_console.router)

from .routes import erp as erp_routes  # noqa: E402  (ERP / Odoo integration, see app/erp/)

app.include_router(erp_routes.router)
app.include_router(company_routes.router)

from .routes import demo as demo_routes  # noqa: E402  (live demo pipeline, see app/demo/)

app.include_router(demo_routes.router)


def _qdrant_status() -> dict:
    # Reuses retriever.get_client()'s cached singleton (written in M2,
    # after this function already existed in M1) rather than opening a
    # second, redundant client — one source of truth for Qdrant connection
    # params, exercised on every /health call instead of only at ingest/diff time.
    try:
        client = retriever.get_client()
        collections = {c.name for c in client.get_collections().collections}
        return {
            "reachable": True,
            "collection_exists": settings.qdrant_collection in collections,
        }
    except Exception as exc:
        return {"reachable": False, "error": f"{type(exc).__name__}: {exc}"}


@app.get("/health")
def health():
    db_ok = db_reachable()
    qdrant = _qdrant_status()
    llm_status = llm.probe()
    ready = db_ok and qdrant["reachable"]
    return {
        "status": "ok" if ready else "degraded",
        "ready": ready,
        "db": {"reachable": db_ok},
        "qdrant": qdrant,
        "llm": llm_status,
    }
