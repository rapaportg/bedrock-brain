# =============================================================================
# bedrock-brain Makefile
# =============================================================================

.PHONY: help up down restart logs build ps shell-api shell-gateway \
        migrate lint test clean keycloak-url minio-url

help:
	@echo ""
	@echo "  bedrock-brain dev commands"
	@echo ""
	@echo "  make up          Start all services"
	@echo "  make down        Stop all services"
	@echo "  make restart     Restart all services"
	@echo "  make build       Rebuild all images"
	@echo "  make logs        Tail logs (all services)"
	@echo "  make ps          Show running containers"
	@echo ""
	@echo "  make shell-api     Shell into brain-api"
	@echo "  make shell-gateway Shell into mcp-gateway"
	@echo ""
	@echo "  make migrate     Run pending DB migrations"
	@echo "  make lint        Run ruff linter on all services"
	@echo "  make test        Run all tests"
	@echo "  make clean       Remove volumes and containers"
	@echo ""
	@echo "  make keycloak-url  Print Keycloak admin URL"
	@echo "  make minio-url     Print MinIO console URL"
	@echo ""

# ---------------------------------------------------------------------------
# Stack lifecycle
# ---------------------------------------------------------------------------

up:
	@cp -n .env.example .env 2>/dev/null || true
	docker compose up -d
	@echo ""
	@echo "  Stack is up."
	@echo "  Brain API:      http://localhost:8000/docs"
	@echo "  MCP Gateway:    http://localhost:8001"
	@echo "  Keycloak admin: http://localhost:8080  (admin / admin)"
	@echo "  MinIO console:  http://localhost:9001  (minioadmin / minioadmin)"
	@echo ""

down:
	docker compose down

restart:
	docker compose restart

build:
	docker compose build --no-cache

logs:
	docker compose logs -f

ps:
	docker compose ps

# ---------------------------------------------------------------------------
# Service shells
# ---------------------------------------------------------------------------

shell-api:
	docker compose exec brain-api bash

shell-gateway:
	docker compose exec mcp-gateway bash

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

migrate:
	docker compose exec brain-api alembic upgrade head

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------

lint:
	docker compose exec brain-api ruff check app
	docker compose exec mcp-gateway ruff check app
	docker compose exec sync-bridge ruff check app

test:
	docker compose exec brain-api pytest tests/ -v
	docker compose exec mcp-gateway pytest tests/ -v
	docker compose exec sync-bridge pytest tests/ -v

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean:
	docker compose down -v --remove-orphans

# ---------------------------------------------------------------------------
# Info
# ---------------------------------------------------------------------------

keycloak-url:
	@echo "Keycloak admin: http://localhost:8080/admin  (admin / admin)"
	@echo "Realm OIDC:     http://localhost:8080/realms/bedrock/.well-known/openid-configuration"

minio-url:
	@echo "MinIO console: http://localhost:9001  (minioadmin / minioadmin)"
	@echo "S3 endpoint:   http://localhost:9000"
