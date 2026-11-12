"""
M6 — the agent loop.

Everything lives in `graph.py` (the LangGraph state machine plus its CLI).
This package deliberately re-exports nothing: importing `app.agent` should
not drag in LangGraph, and callers that want the loop say so explicitly —

    from app.agent.graph import run_once, resume_run, detect_new_sources

See `graph.py`'s module docstring for the state machine, the human-review
interrupt, and how the pieces M4/M5 own are called.
"""
