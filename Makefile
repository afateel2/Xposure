.PHONY: install dev backend frontend infra infra-down ingest-demo diff-demo eval test clean

# macOS/Linux convenience wrapper. Windows: use start.ps1 (make isn't a
# stock Windows tool — see docs/PLAN.md M1).

install:
	cd backend && pip install -r requirements.txt && playwright install chromium
	cd frontend && npm install

infra:
	docker compose up -d

infra-down:
	docker compose down

backend:
	cd backend && uvicorn app.main:app --port 8010 --host 0.0.0.0 --reload

frontend:
	cd frontend && npm run dev

dev:
	@echo "Starting backend and frontend in the background — logs interleave; Ctrl+C stops both."
	@( cd backend && uvicorn app.main:app --port 8010 --host 0.0.0.0 --reload & )
	@( cd frontend && npm run dev & )
	@wait

ingest-demo:
	cd backend && python -m app.ingest --regulator nca --regulation ecc --version 1-2018 --file "data/sources/nca/Essential Cybersecurity Controls (ECC-1-2018).pdf"
	cd backend && python -m app.ingest --regulator nca --regulation ecc --version 2-2024 --file "data/sources/nca/Essential Cybersecurity Controls (ECC-2-2024).pdf" --code-before-text

# M3+: python -m app.diff --regulation ecc --from 1-2018 --to 2-2024
diff-demo:
	cd backend && python -m app.diff --regulation ecc --from 1-2018 --to 2-2024

# M9+: benchmarks every model in LLM_MODEL's candidate list via OpenRouter
eval:
	cd backend && python -m tests.eval_diff

test:
	cd backend && pytest tests/unit -q
	cd frontend && npm run lint

clean:
	docker compose down -v
