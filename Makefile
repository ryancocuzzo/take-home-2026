.PHONY: backend frontend

backend:
	uv run uvicorn backend.api.api:app --port 8000

frontend:
	cd frontend && npm run dev -- --port 3000
