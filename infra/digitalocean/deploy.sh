#!/usr/bin/env bash
# =============================================================================
# bedrock-brain — deploy / update script
#
# Usage:
#   bash infra/digitalocean/deploy.sh              # pull latest + restart
#   bash infra/digitalocean/deploy.sh --first-run  # first-time: get SSL certs
#
# Environment variables (set by CI via SSH envs, or manually for rollback):
#   DEPLOY_TAG        — git SHA of the images to pull (default: latest)
#   DO_API_TOKEN      — DigitalOcean API token for DOCR authentication
#   DO_REGISTRY_NAME  — DOCR registry slug, e.g. "bedrock"
#
# Rollback to a previous release:
#   DEPLOY_TAG=<previous-sha> DO_API_TOKEN=<token> DO_REGISTRY_NAME=<name> \
#       bash /opt/bedrock-brain/infra/digitalocean/deploy.sh
#
# Run as the deploy user (or root during initial setup).
# =============================================================================

set -euo pipefail

APP_DIR="/opt/bedrock-brain"
COMPOSE="docker compose -f docker-compose.yml -f infra/digitalocean/docker-compose.prod.yml"
FIRST_RUN=false

for arg in "$@"; do
    [[ "$arg" == "--first-run" ]] && FIRST_RUN=true
done

cd "${APP_DIR}"

# Load env to read domain names and DB credentials
set -o allexport
# shellcheck disable=SC1091
source .env
set +o allexport

echo "=========================================="
echo "  bedrock-brain deploy — $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "=========================================="

# ---------------------------------------------------------------------------
# Pull latest scripts / compose files (images come from DOCR, not built here)
# ---------------------------------------------------------------------------
echo "[1] Pulling latest from origin/main..."
git fetch origin
git reset --hard origin/main

# ---------------------------------------------------------------------------
# DOCR login
# ---------------------------------------------------------------------------
echo "[2] Logging in to DOCR..."
echo "${DO_API_TOKEN}" | docker login registry.digitalocean.com \
    -u "${DO_API_TOKEN}" --password-stdin

# ---------------------------------------------------------------------------
# Set image coordinates
# ---------------------------------------------------------------------------
export REGISTRY="registry.digitalocean.com/${DO_REGISTRY_NAME}"
export IMAGE_TAG="${DEPLOY_TAG:-latest}"
echo "    Registry : ${REGISTRY}"
echo "    Image tag: ${IMAGE_TAG}"

# ---------------------------------------------------------------------------
# Pull pre-built images from DOCR
# ---------------------------------------------------------------------------
echo "[3] Pulling images (tag: ${IMAGE_TAG})..."
${COMPOSE} pull brain-api mcp-gateway sync-bridge brain-web

# ---------------------------------------------------------------------------
# First-run: start nginx over HTTP only, get SSL certs, then enable HTTPS
# ---------------------------------------------------------------------------
if [[ "${FIRST_RUN}" == "true" ]]; then
    echo "  First-run: obtaining Let's Encrypt certificates..."

    echo "  Starting nginx for ACME challenge..."
    ${COMPOSE} up -d nginx

    for DOMAIN in "${APP_DOMAIN}" "${API_DOMAIN}" "${AUTH_DOMAIN}" "${MCP_DOMAIN}"; do
        echo "  Issuing cert for ${DOMAIN}..."
        docker compose run --rm certbot certonly \
            --webroot \
            --webroot-path=/var/www/certbot \
            --email "${CERTBOT_EMAIL:-admin@${APP_DOMAIN}}" \
            --agree-tos \
            --no-eff-email \
            -d "${DOMAIN}"
    done

    echo "  Certs issued. Reloading nginx with HTTPS config..."
fi

# ---------------------------------------------------------------------------
# Bring up the full stack (no build — images are already pulled from DOCR)
# ---------------------------------------------------------------------------
echo "[4] Starting / restarting services..."
${COMPOSE} up -d --remove-orphans --no-build

# ---------------------------------------------------------------------------
# Run DB migrations (idempotent — skips already-applied files)
# ---------------------------------------------------------------------------
echo "[5] Running database migrations..."
sleep 5   # give postgres a moment if it just started
bash "${APP_DIR}/infra/digitalocean/migrate.sh"

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
echo "[6] Checking service health..."
sleep 8
${COMPOSE} ps

API_URL="http://localhost:8000/healthz"
if curl -sf "${API_URL}" >/dev/null; then
    echo "  brain-api: healthy"
else
    echo "  WARNING: brain-api health check failed — check logs:"
    echo "  docker compose logs brain-api --tail=50"
fi

echo ""
echo "  Deploy complete! (image tag: ${IMAGE_TAG})"
echo "  App:      https://${APP_DOMAIN}"
echo "  API docs: https://${API_DOMAIN}/docs"
echo "  Auth:     https://${AUTH_DOMAIN}/admin"
echo "  MCP:      https://${MCP_DOMAIN}"
echo ""
echo "  Rollback: DEPLOY_TAG=<previous-sha> bash infra/digitalocean/deploy.sh"
echo "=========================================="
