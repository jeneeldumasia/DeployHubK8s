.PHONY: up down build logs backend frontend

up:
	docker-compose up -d

down:
	docker-compose down

build:
	docker-compose build

logs:
	docker-compose logs -f

backend:
	cd backend && uvicorn main:app --reload

frontend:
	cd frontend && npm run dev
