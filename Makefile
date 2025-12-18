.PHONY: help build up down logs shell test-db dev dev-run dev-shell dev-logs dev-stop prod

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build the Docker image
	docker-compose build

up: ## Start worker in production mode
	docker-compose up

down: ## Stop and remove containers
	docker-compose down

logs: ## View worker logs
	docker-compose logs -f worker

shell: ## Get a shell in the running container
	docker-compose exec worker /bin/bash

test-db: ## Test database connection
	docker-compose -f docker-compose.dev.yml exec worker python db.py

dev: ## Start dev container in background (keeps container running)
	docker-compose -f docker-compose.dev.yml up -d

dev-run: ## Run the worker in the dev container
	docker-compose -f docker-compose.dev.yml exec worker python worker.py

dev-shell: ## Get a shell in dev container
	docker-compose -f docker-compose.dev.yml exec worker /bin/bash

dev-logs: ## View dev container logs
	docker-compose -f docker-compose.dev.yml logs -f worker

dev-stop: ## Stop dev container
	docker-compose -f docker-compose.dev.yml down

prod: ## Build and run in production mode
	docker-compose up --build -d

