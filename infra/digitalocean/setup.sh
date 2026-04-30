#!/usr/bin/env bash
# =============================================================================
# bedrock-brain — Droplet bootstrap (run once on a fresh Ubuntu 22.04 Droplet)
#
# Usage:
#   ssh root@<droplet-ip> 'bash -s' < infra/digitalocean/setup.sh
#
# What it does:
#   1. Updates the system
#   2. Installs Docker + Docker Compose plugin
#   3. Creates a non-root deploy user
#   4. Hardens SSH (disable root login, disable password auth)
#   5. Configures UFW firewall (22, 80, 443)
#   6. Clones the repo and scaffolds .env
# =============================================================================

set -euo pipefail

# Force fully non-interactive apt/dpkg behavior so this script can be piped
# over SSH without a TTY (no sshd_config conffile prompt, no needrestart UI).
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
export NEEDRESTART_SUSPEND=1
export APT_LISTCHANGES_FRONTEND=none
APT_OPTS=(-y -qq \
    -o Dpkg::Options::=--force-confold \
    -o Dpkg::Options::=--force-confdef)

REPO_URL="${REPO_URL:-https://github.com/YOUR_USERNAME/bedrock-brain.git}"
DEPLOY_USER="${DEPLOY_USER:-deploy}"
APP_DIR="/opt/bedrock-brain"

echo "=========================================="
echo "  bedrock-brain Droplet setup"
echo "=========================================="

# ---------------------------------------------------------------------------
# 1. System update
# ---------------------------------------------------------------------------
echo "[1/6] Updating system packages..."
apt-get update -qq
apt-get upgrade "${APT_OPTS[@]}"
apt-get install "${APT_OPTS[@]}" \
    curl git ufw fail2ban \
    ca-certificates gnupg lsb-release

# ---------------------------------------------------------------------------
# 2. Docker
# ---------------------------------------------------------------------------
echo "[2/6] Installing Docker..."
if ! command -v docker &>/dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --batch --yes --no-tty --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu \
        $(lsb_release -cs) stable" \
        | tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -qq
    apt-get install "${APT_OPTS[@]}" docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
systemctl enable --now docker
echo "  Docker $(docker --version) installed."

# ---------------------------------------------------------------------------
# 3. Deploy user
# ---------------------------------------------------------------------------
echo "[3/6] Creating deploy user: ${DEPLOY_USER}..."
if ! id "${DEPLOY_USER}" &>/dev/null; then
    useradd -m -s /bin/bash "${DEPLOY_USER}"
    usermod -aG docker "${DEPLOY_USER}"
fi

# Copy authorized_keys from root so the deploy user can SSH in
mkdir -p "/home/${DEPLOY_USER}/.ssh"
if [[ -f /root/.ssh/authorized_keys ]]; then
    cp /root/.ssh/authorized_keys "/home/${DEPLOY_USER}/.ssh/authorized_keys"
    chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "/home/${DEPLOY_USER}/.ssh"
    chmod 700 "/home/${DEPLOY_USER}/.ssh"
    chmod 600 "/home/${DEPLOY_USER}/.ssh/authorized_keys"
fi

# ---------------------------------------------------------------------------
# 4. SSH hardening
# ---------------------------------------------------------------------------
echo "[4/6] Hardening SSH..."
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl reload sshd

# ---------------------------------------------------------------------------
# 5. Firewall
# ---------------------------------------------------------------------------
echo "[5/6] Configuring UFW firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp   comment "SSH"
ufw allow 80/tcp   comment "HTTP for Lets Encrypt and redirect"
ufw allow 443/tcp  comment "HTTPS"
ufw --force enable
echo "  UFW status:"
ufw status numbered

# ---------------------------------------------------------------------------
# 6. Clone repo
# ---------------------------------------------------------------------------
echo "[6/6] Cloning repo to ${APP_DIR}..."
if [[ ! -d "${APP_DIR}" ]]; then
    git clone "${REPO_URL}" "${APP_DIR}"
fi
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${APP_DIR}"

# Scaffold .env from DO example if not present
if [[ ! -f "${APP_DIR}/.env" ]]; then
    cp "${APP_DIR}/infra/digitalocean/.env.do.example" "${APP_DIR}/.env"
    echo ""
    echo "  *** ACTION REQUIRED: edit ${APP_DIR}/.env with your real values ***"
fi

echo ""
echo "=========================================="
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "  1. Edit ${APP_DIR}/.env"
echo "  2. Point your DNS A records at this Droplet's IP"
echo "  3. Run: bash ${APP_DIR}/infra/digitalocean/deploy.sh --first-run"
echo "=========================================="
