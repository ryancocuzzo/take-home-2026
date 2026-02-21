.PHONY: backend frontend test test-eval test-all

backend:
	uv run uvicorn backend.api.api:app --port 8000

frontend:
	cd frontend && npm run dev -- --port 3000

test-unit:
	uv run pytest tests/ -v -s

test-eval:
	uv run pytest tests/evals/ -v -s -m slow

test-all:
	uv run pytest tests/ -v -s -m ""