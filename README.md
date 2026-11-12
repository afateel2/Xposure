# Xposure

An AI agent for regulatory change monitoring, built for Saudi industrial and defense organizations. It reads a regulator's new edition, finds exactly what changed, traces what that touches inside the organization, and acts on it with a human approving every step. Bilingual UI (Arabic RTL primary, English secondary).

---

## The problem

Regulators (starting with NCA's Essential Cybersecurity Controls) update their requirements periodically, and every update can quietly change what an organization is legally required to do. Today that means someone manually re-reading a new PDF against the old one, clause by clause, guessing at what actually changed, and then guessing again at which internal policies, systems, or teams it affects. It's slow, easy to get wrong, and a missed change carries real financial and reputational risk (non-compliance has been measured at 2.71 times the cost of compliance; Ponemon Institute and Globalscape, 2017).

## The solution

Xposure automates that whole chain:

1. **Ingests** a regulation's source PDF into a versioned, structured store (one row per clause).
2. **Diffs** two versions of the same regulation clause-by-clause (exact match + embedding similarity for renumbered clauses), then an LLM classifies *what kind* of change it is (tightened, relaxed, clarified, new obligation, etc.) and writes a plain-language summary. The LLM only ever labels a change that deterministic code already found; it never invents one.
3. **Traces impact** through the organization's own graph of policies, processes, systems, and owners, so each change comes with *specific* items it affects, not a generic notice.
4. **Prioritizes** every resulting action with a deterministic score (change severity × how much of the org it reaches × how close the deadline is), never left to the LLM's judgment.
5. **Routes** each action through an automation policy: some are safe to auto-execute, most go to a human to approve, dismiss, or delegate to someone else, with a full audit trail either way.

6. **Acts, with a human in charge.** When a person approves "Let the agent handle it" on a policy, procedure or configuration action, the agent edits the matching company document inside a sandboxed folder. Every edit is versioned, shown as a diff, and can be undone. Actions that belong to a person are escalated as real tasks in an ERP (Odoo), and the task's status flows back into Xposure.
7. **Keeps you informed.** The dashboard shows what the agent is doing right now, when each regulator was last checked, when its last change was detected, a live activity feed, per-change timelines, task statuses and a searchable audit log.

The trust rule is simple: the agent proposes, a human approves. Nothing is written until a person says so, writes stay inside a sandbox, every write is reversible, and every step is recorded.

Everything is exportable (PDF report, Excel worklist, OSCAL-flavored JSON) and every step is logged, so a compliance officer can reconstruct exactly what the system saw and decided, and why.

## Tech stack

| Layer | What it is | What it's for |
|---|---|---|
| **FastAPI** (Python) | Backend web framework | The REST API and all business logic |
| **PostgreSQL 16** | Relational database | Stores regulations, clauses, the org graph, changes, actions, and the audit log |
| **SQLAlchemy + Alembic** | ORM + migrations | Python models for the above, with versioned schema migrations |
| **Qdrant** | Vector database | Stores clause embeddings so renumbered/reworded clauses can still be matched across versions |
| **multilingual-e5-large** | Embedding model | Turns clause text into the vectors Qdrant searches |
| **An OpenAI-compatible LLM** (local Ollama, or a cloud provider for dev) | Language model | Classifies each change and writes human-readable summaries/impact notes, never decides facts, only labels what code already computed |
| **LangGraph** | Agent orchestration | Runs the ingest → diff → impact → prioritize → policy pipeline as a real, resumable multi-step graph, including a genuine pause for human approval |
| **Next.js 15 / React 19 / TypeScript** | Frontend framework | The bilingual (Arabic RTL / English) web UI |
| **Playwright (headless Chromium)** | Browser automation | Renders the HTML-based PDF/report exports |
| **Docker Compose** | Containerization | Runs Postgres and Qdrant locally with one command, and Odoo (optional profile) for the ERP demo |
| **Odoo 17** (official Docker image, optional) | ERP | Receives escalated actions as real tasks and reports their status back |

## Requirements to run the system

**Prerequisites:**
- Python 3.12+
- Node.js 18+
- Docker Desktop
- An LLM endpoint, either a local [Ollama](https://ollama.com) install (no API key needed, no data leaves the machine), or an API key for a cloud OpenAI-compatible provider (useful for development on a machine that can't run larger models locally)

**One-time setup:**
```bash
cp .env.example .env          # then fill in LLM_BASE_URL/LLM_API_KEY/LLM_MODEL if not using the defaults
cd backend && pip install -r requirements.txt && cd ..
cd frontend && npm install && cd ..
cd backend && alembic upgrade head && python scripts/seed_users.py && cd ..   # six named reviewers, see below
```

**Signing in.** Every state-changing action (approve, dismiss, delegate, undo, run a scan, edit the automation policy) requires a real signed-in reviewer; dashboards, reports and the audit log stay readable without signing in. `scripts/seed_users.py` creates six named reviewers (the same people seeded into Odoo by `scripts/odoo_seed.py`, same emails) and writes one shared password to `.env` as `DEMO_USER_PASSWORD`. Open `/login`, pick a name (fills the email) and enter that password. The Compliance Officer is the one admin-role account, and can edit the automation policy from Settings.

**Start everything:**
```powershell
./start.ps1        # Windows
```
```bash
./start.sh          # macOS / Linux
```
This boots Postgres + Qdrant (Docker), the backend, and the frontend, with a health check at each layer. Each service opens in its own terminal window so logs stay visible.

Or start each piece by hand:
```bash
docker compose up -d
cd backend && uvicorn app.main:app --port 8010 --host 0.0.0.0            # separate terminal (no --reload, see the caution below)
cd frontend && npm run dev                                               # separate terminal
```

**Verify it's running:** backend health check at `http://127.0.0.1:8010/health` (reports Postgres/Qdrant/LLM reachability), frontend at `http://localhost:3010`.

**Windows note:** `./stop.ps1` stops the backend/frontend cleanly, including orphaned worker processes that sometimes outlive a killed parent and keep answering requests on the same port with stale code, a real, repeat gotcha on Windows. Run it before restarting either server.

**A caution on `--reload`:** on at least one development machine, `uvicorn --reload` has been observed to silently fail to complete a reload, it logs that it detected a file change and is reloading, but never finishes, and the old process keeps answering requests indefinitely with no error. If backend changes don't seem to be taking effect, don't assume the code is wrong, stop the process fully and start it fresh before debugging further. For a live demo, prefer running without `--reload` and restarting manually after any change.

### Guided demo (company on ECC-1:2018, then a live scan for ECC-2:2024)

The app ships with a small fictional company, **Eastern Industrial Company** (an industrial electronics manufacturer in Dammam), that currently follows **ECC-1:2018**. The Run agent page tells the story end to end:

1. Press **Reset demo**. The company is back on ECC-1:2018, its documents are restored, and no changes are shown.
2. Press **Scan now**. The agent checks the regulator portal, fetches **ECC-2:2024**, and runs the real pipeline (ingest, align, classify, impact, prioritize, policy) with live progress. In the guided demo the portal is replayed from a local folder (`backend/data/portal_mirror/`) holding NCA's real, official PDF, so a scan is fast and repeatable; a real on-demand check against NCA's own public page is on the Sources screen.
3. Open **Changes**. Pick ECC-2:2024 clause 2-5-3-9 (DDoS protection, a new obligation). On the Network Security Procedure, press **Let the agent handle it**: the agent edits the procedure document, shows the diff, and offers **Undo**. See the result in **Facility profile**, with its version history.
4. On the IT Security Lead, press **Assign to a person**. The agent has already read the organization graph and suggests who owns the affected item; confirm or change it, choose **Send to ERP (Odoo)**, and send. A real task appears in Odoo (Project, Compliance Actions). Move it to Done in Odoo, sync, and the Xposure action closes with an audit row.

Set up for the demo:
```bash
docker compose up -d                                   # Postgres and Qdrant
docker compose --profile odoo up -d odoo-db odoo       # Odoo 17 on http://127.0.0.1:8069 (official images, local only)
cd backend && python scripts/odoo_seed.py               # employees and the Compliance Actions project (first time only)
python -m app.demo.prepare                              # optional: warm the local result cache (about 6 minutes)
```
The demo uses a local cache of earlier identical model answers so a replay takes about 45 seconds instead of tens of minutes. The run log states how many answers came from the cache. Remove Odoo and its data with `docker compose --profile odoo down -v`.

**Loading in a regulation manually:** the app starts with an empty database. Two example NCA ECC source PDFs are provided in `backend/data/sources/nca/` (not committed to git, see `.gitignore`):
```bash
cd backend
python -m app.ingest --regulator nca --regulation ecc --version 1-2018 --file "data/sources/nca/Essential Cybersecurity Controls (ECC-1-2018).pdf"
python -m app.ingest --regulator nca --regulation ecc --version 2-2024 --file "data/sources/nca/Essential Cybersecurity Controls (ECC-2-2024).pdf" --code-before-text
```
Then run the agent pipeline to actually diff, classify, and generate actions:
```bash
python -m app.agent.graph
```

macOS/Linux convenience wrapper for all of the above: `make install`, `make infra`, `make dev`, `make test`, `make ingest-demo` (see `Makefile`).

### What actually happens when you run that

The two files above are two real editions of the same regulation: **ECC-1:2018**, NCA's original Essential Cybersecurity Controls, and **ECC-2:2024**, its 2024 revision. Running the two `ingest` commands stores each one as its own version, clause by clause (246 and 233 clauses respectively), nothing is compared yet, they're just recorded.

`python -m app.agent.graph` is where the actual simulation happens, in order:

1. **Diff.** Every clause in ECC-1:2018 is matched against its counterpart in ECC-2:2024, first by exact control-ID (e.g. clause `2-5-3` in one edition against `2-5-3` in the other), then by embedding similarity for anything that was renumbered. On the real ECC documents this finds roughly 230 exact-ID matches, a few newly introduced clauses, and around 16 clauses that were withdrawn outright.
2. **Classify.** For every matched (or added/withdrawn) clause pair, the LLM reads only the old and new text and labels the change (`tightened`, `relaxed`, `clarification`, `new_obligation`, `editorial`, `renumbered`, `withdrawn`) and writes a one-line summary in both languages. It never sees or touches any clause it wasn't handed.
3. **Impact.** Every change classified as materially significant gets traced through the demo organization's own graph (Eastern Industrial Company, a fictional industrial electronics manufacturer seeded in `backend/data/org/demo_org.yaml`) to find which specific policies, processes, systems, and owners it actually touches, a change to an access-control clause, for instance, shows up against the Information Security Policy and whichever systems it governs, not as a generic "something changed" notice.
4. **Prioritize + act.** Each impacted item gets a deterministic priority score, and an action (update a policy, collect evidence, reassess a control, notify an owner, etc.) is created and routed through the automation policy, most pause for a human to approve, dismiss, or delegate; a narrow, explicitly safe subset auto-executes.

A full real run over these two documents produces 208 classified clause changes (roughly 90 of them material), around 400 impacted items in the demo company, and about 600 resulting actions, almost all routed to a human, with a small explicitly safe set auto-executed and recorded only. Open the frontend afterward to see them, or add `--replace` to `ingest` and re-run if you want to try it again from a clean slate.

### More capabilities

- **The agent shows its reasoning.** Every change carries its classification confidence against the auto-execute threshold and a "why this priority" breakdown (severity, reach, deadline, regulator weight). Every action records which policy gates set its automation level, and the full breakdown is written to the audit trail, not just shown on screen.
- **The agent suggests who should act.** When an action needs a person, the agent reads the organization graph and pre-fills the owner of the affected item; the reviewer confirms or overrides it before anything is sent.
- **A review workflow.** A review queue across changes, a dismiss dialog that requires a reason (kept in the audit log), and citation badges that check each quoted clause against the source text.
- **A second real regulator.** SASO's Technical Regulation for Restriction of Hazardous Substances in Electrical and Electronic Equipment (RoHS), directly relevant to the demo company's own products. Sourced from `saso.gov.sa` itself, not a mirror, and ingested with a dedicated parser for its Article-numbered shape (`app/ingest_articles.py`), a different document structure from NCA ECC's two-column table:
  ```bash
  cd backend
  python -m app.ingest_articles --regulator saso --regulation rohs --version 2-2022 --spec saso_rohs \
      --file "data/sources/saso/TR-Restriction-of-hazardous-Substance-in-Electrical-and-Electronic-Equipment-V2.pdf"
  ```
- **A live portal check.** `POST /sources/check-live` (the Sources screen's "Check now" button, sign-in required) makes one real, on-demand request to the regulator's own public page, compares the live version and file hash against what is ingested, and reports honestly: a new edition is live, the ingested copy matches, or the content has drifted under the same label. It never ingests anything automatically and is never scheduled, a detected new version still needs a human to run `ingest`. Wired up for NCA/ECC so far (`app/watcher.py`).
- **Real reviewer identity.** Every approval, dismissal, delegation and policy edit is attributed to one of six named, signed-in reviewers (`POST /auth/login`, the `/login` page), not a fixed placeholder actor. The automation policy is now editable from Settings, admin role only.

---

## Learn more

The app itself carries its guides: **User guide** (`/help`), **Deployment** (`/deployment`, on-premise and cloud options), and **Integrations** (`/integrations`, ERP and GRC connectors). The public overview page is `/welcome`.

## Attribution

Several backend modules are ported from **ComplyX** (ضامن), a prior project by the same author.
