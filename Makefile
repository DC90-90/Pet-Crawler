.PHONY: help install up db seed admin backend frontend dev \
	test test-backend test-frontend e2e lint format build reset

help:
	@echo "Svaneti with Georgie — make targets:"
	@echo "  install        Install backend (pip) + frontend (npm) deps"
	@echo "  up             docker compose up (mongo + backend + frontend)"
	@echo "  db             Start MongoDB only (docker)"
	@echo "  seed           Seed the database"
	@echo "  admin          Create/update the owner account"
	@echo "  backend        Run FastAPI dev server (:8000)"
	@echo "  frontend       Run Vite dev server (:5173)"
	@echo "  dev            Run backend + frontend together"
	@echo "  test           Run backend + frontend unit tests"
	@echo "  e2e            Run Playwright end-to-end tests"
	@echo "  lint / format  Lint / format both stacks"
	@echo "  build          Production builds"
	@echo "  reset          Drop the dev database volume"

install:
	cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
	cd frontend && npm install

up:
	docker compose up

db:
	docker compose up -d mongo

seed:
	cd backend && python -m app.seed.run

admin:
	python -m scripts.create_admin

backend:
	cd backend && uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

dev:
	@echo "Starting backend (:8000) and frontend (:5173). Ctrl-C to stop."
	@bash -c 'cd backend && uvicorn app.main:app --reload --port 8000 & \
	(cd frontend && npm run dev) & wait'

test: test-backend test-frontend

test-backend:
	cd backend && pytest -q

test-frontend:
	cd frontend && npm run test

e2e:
	cd frontend && npm run test:e2e

lint:
	cd backend && ruff check .
	cd frontend && npm run lint

format:
	cd backend && ruff format .
	cd frontend && npm run format

build:
	cd frontend && npm run build
	docker compose build

reset:
	docker compose down -v
