#!/usr/bin/env bash
# =============================================================================
# bedrock-brain — idempotent SQL migration runner
#
# Applies any db/migrations/*.sql files that haven't been recorded in the
# schema_migrations table. Files are applied in filename (alphabetical) order.
#
# Safe to run on every deploy — already-applied migrations are skipped.
# Called automatically by deploy.sh after services start.
# =============================================================================

set -euo pipefail

APP_DIR="/opt/bedrock-brain"
COMPOSE="docker compose -f docker-compose.yml -f infra/digitalocean/docker-compose.prod.yml"
DB_USER="${POSTGRES_USER:-bedrock}"
DB_NAME="${POSTGRES_DB:-bedrock}"
PSQL="${COMPOSE} exec -T postgres psql -U ${DB_USER} -d ${DB_NAME}"

cd "${APP_DIR}"

# Ensure migration tracking table exists
${PSQL} <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   TEXT        PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
SQL

echo "  Checking migrations in db/migrations/..."

for f in db/migrations/*.sql; do
    fname=$(basename "${f}")
    applied=$(${PSQL} -tAc \
        "SELECT COUNT(*) FROM schema_migrations WHERE filename = '${fname}'")
    if [[ "${applied}" == "0" ]]; then
        echo "  Applying ${fname}..."
        ${PSQL} < "${f}"
        ${PSQL} -c "INSERT INTO schema_migrations(filename) VALUES ('${fname}')"
        echo "  Applied  ${fname}"
    else
        echo "  Skip     ${fname} (already applied)"
    fi
done

echo "  Migrations complete."
