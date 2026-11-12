from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file: backend/app/config.py -> backend/ -> xposure/
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # ── Postgres ──────────────────────────────────────────────────────────
    database_url: str = "postgresql+psycopg://xposure:xposure@127.0.0.1:5442/xposure"

    # ── Qdrant ────────────────────────────────────────────────────────────
    qdrant_host: str = "127.0.0.1"  # not "localhost" — see .env.example
    qdrant_port: int = 6343
    qdrant_collection: str = "xposure_regulations"

    # ── Embeddings ────────────────────────────────────────────────────────
    embedding_model: str = "intfloat/multilingual-e5-large"

    # ── LLM: one OpenAI-compatible client, two valid configurations ─────────
    # Fully local (no cloud LLM calls, nothing leaves the machine):
    #   LLM_BASE_URL=http://localhost:11434/v1 (Ollama)
    # Dev/benchmark only (for machines that can't run the candidate models
    # locally at usable speed): LLM_BASE_URL=https://openrouter.ai/api/v1
    llm_base_url: str = "http://127.0.0.1:11434/v1"  # not "localhost" — see .env.example
    llm_api_key: str = "ollama"  # Ollama ignores the key; required placeholder for the OpenAI client
    llm_model: str = "qwen3.6:27b"

    # ── Company workspace (the demo company's editable documents) ─────────
    # Empty means the default under backend/data/. COMPANY_DIR lets tests
    # and experiments point the agent at a throwaway copy so the real
    # working copy is never dirtied. See app/company/store.py.
    company_dir: str = ""
    company_baseline_dir: str = ""
    company_cache_dir: str = ""

    # ── Demo mode (see app/demo/) ─────────────────────────────────────────
    # Gates the destructive /demo/reset and /demo/scan endpoints and the
    # persistent LLM result cache. Default on for dev; set DEMO_MODE=false
    # for anything that must not be resettable.
    demo_mode: bool = True
    # Pause between visible pipeline stages so a recorded demo is watchable.
    # Real work is never slowed or skipped; the log says the pause exists.
    demo_stage_pacing_ms: int = 600
    # Where the one-time pre-reset pg_dump lands. Empty: backend/data/cache/demo_backups.
    demo_backup_dir: str = ""
    # Docker container used for pg_dump when no local pg_dump is on PATH.
    demo_pg_container: str = "xposure-postgres-1"

    # ── App ───────────────────────────────────────────────────────────────
    corpus_version: str = "2026-09"

    # ── Outbound webhook (M8) ────────────────────────────────────────────
    # Empty by default: webhook sending is a no-op until an operator opts
    # in, never a hard dependency of the core pipeline (see app/webhooks.py).
    webhook_url: str = ""
    webhook_secret: str = ""

    # ── Outbound notification (delegation) ───────────────────────────────
    # Same "opt-in, never a hard dependency" shape as the webhook settings
    # above — empty by default, honest no-op until configured (see
    # app/notify.py). notification_channel is currently only "email"
    # (SMTP); anything else (including "") means no channel configured.
    notification_channel: str = ""
    notification_from: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""

    # ── Digest recipient ──────────────────────────────────────────────────
    # Empty by default, same opt-in shape: `python -m app.digest` is a no-op
    # delivery target until an operator sets this (see app/digest.py).
    digest_recipient: str = ""


settings = Settings()
