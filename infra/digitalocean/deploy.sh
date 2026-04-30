#!/usr/bin/env bash
# =============================================================================
# bedrock-brain — deploy / update script
#
# Usage:
#   bash infra/digitalocean/deploy.sh              # pull latest + restart
#   bash infra/digitalocean/deploy.sh --first-run  # first-time: get SSL certs
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

# Load env to read domain names
set -o allexport
# shellcheck disable=SC1091
source .env
set +o allexport

echo "=========================================="
echo "  bedrock-brain deploy — $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "=========================================="

# ---------------------------------------------------------------------------
# Pull latest code
# ---------------------------------------------------------------------------
echo "[1] Pulling latest from origin/main..."
git fetch origin
git reset --hard origin/main

# ---------------------------------------------------------------------------
# Build images
# ---------------------------------------------------------------------------
echo "[2] Building images..."
${COMPOSE} build \
    --build-arg VITE_API_BASE_URL="${VITE_API_BASE_URL:-https://${API_DOMAIN}}" \
    --build-arg VITE_KEYCLOAK_URL="${VITE_KEYCLOAK_URL:-https://${AUTH_DOMAIN}}" \
    --build-arg VITE_KEYCLOAK_REALM="${VITE_KEYCLOAK_REALM:-bedrock}" \
    --build-arg VITE_KEYCLOAK_CLIENT_ID="${VITE_KEYCLOAK_CLIENT_ID:-brain-ui}"

# ---------------------------------------------------------------------------
# First-run: start nginx over HTTP only, get SSL certs, then enable HTTPS
# ---------------------------------------------------------------------------
if [[ "${FIRST_RUN}" == "true" ]]; then
    echo "[3] First-run: obtaining Let's Encrypt certificates..."

    # Temporarily use HTTP-only nginx config to pass ACME challenge
    echo "  Starting nginx for ACME challenge..."
    ${COMPOSE} up -d nginx

    # Issue certs for all four subdomains
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
# Bring up the full stack
# ---------------------------------------------------------------------------
echo "[3] Starting / restarting services..."
${COMPOSE} up -d --remove-orphans

# ---------------------------------------------------------------------------
# Run DB migrations
# ---------------------------------------------------------------------------
echo "[4] Running database migrations..."
sleep 5   # give postgres a moment if it just started
${COMPOSE} exec -T brain-api alembic upgrade head

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
echo "[5] Checking service health..."
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
echo "  Deploy complete!"
echo "  App:      https://${APP_DOMAIN}"
echo "  API docs: https://${API_DOMAIN}/docs"
echo "  Auth:     https://${AUTH_DOMAIN}/admin"
echo "  MCP:      https://${MCP_DOMAIN}"
echo "=========================================="
