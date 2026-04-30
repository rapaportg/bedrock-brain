# Deploying bedrock-brain on DigitalOcean

This guide covers deploying the full bedrock-brain stack on a single DigitalOcean Droplet with:
- **Docker Compose** for orchestration
- **DigitalOcean Spaces** for S3-compatible object storage (replaces MinIO)
- **nginx + Let's Encrypt** for SSL termination
- **Keycloak** for OIDC auth

---

## Prerequisites

- A DigitalOcean account
- A domain you control (e.g. `yourdomain.com`)
- Your SSH public key added to DO

---

## Step 1 — Create DigitalOcean Spaces bucket

1. Go to **Spaces Object Storage** → **Create a Space**
2. Choose a region (e.g. `nyc3`) — pick the same region as your Droplet
3. Name it `bedrock-brain` (or any name — update `S3_BUCKET_NAME` in `.env`)
4. Set **File Listing** to **Restricted**
5. Go to **API → Spaces Keys** → Generate a new key
6. Save the **Access Key** and **Secret Key** — you'll need them in Step 3

---

## Step 2 — Provision a Droplet

Recommended spec for MVP (10–50 users):

| Field       | Value                     |
|-------------|---------------------------|
| Image       | Ubuntu 22.04 LTS          |
| Size        | 4 GB RAM / 2 vCPU ($24/mo)|
| Region      | Same as your Spaces bucket|
| Auth        | SSH Key (your key)        |

Note the Droplet's **public IP address**.

---

## Step 3 — Point DNS at the Droplet

Create four **A records** in your DNS provider pointing to the Droplet IP:

| Record              | Type | Value         |
|---------------------|------|---------------|
| `app.yourdomain.com`  | A    | `<droplet-ip>` |
| `api.yourdomain.com`  | A    | `<droplet-ip>` |
| `auth.yourdomain.com` | A    | `<droplet-ip>` |
| `mcp.yourdomain.com`  | A    | `<droplet-ip>` |

DNS propagation can take a few minutes. You can check with:
```bash
dig app.yourdomain.com +short
```

---

## Step 4 — Bootstrap the Droplet

Run the setup script from your local machine:

```bash
# Clone locally if you haven't already
git clone https://github.com/YOUR_USERNAME/bedrock-brain.git
cd bedrock-brain

# Run setup on the Droplet (replace with your Droplet IP)
REPO_URL=https://github.com/YOUR_USERNAME/bedrock-brain.git \
  ssh root@<droplet-ip> 'bash -s' < infra/digitalocean/setup.sh
```

This installs Docker, creates a `deploy` user, hardens SSH, and configures UFW.

---

## Step 5 — Configure environment

SSH into the Droplet as the deploy user and edit `.env`:

```bash
ssh deploy@<droplet-ip>
nano /opt/bedrock-brain/.env
```

Fill in these values (at minimum):

```bash
# Domains
APP_DOMAIN=app.yourdomain.com
API_DOMAIN=api.yourdomain.com
AUTH_DOMAIN=auth.yourdomain.com
MCP_DOMAIN=mcp.yourdomain.com
KEYCLOAK_PUBLIC_HOST=auth.yourdomain.com

# DigitalOcean Spaces (from Step 1)
S3_ENDPOINT_URL=https://nyc3.digitaloceanspaces.com
S3_ACCESS_KEY_ID=<your-spaces-access-key>
S3_SECRET_ACCESS_KEY=<your-spaces-secret-key>
S3_BUCKET_NAME=bedrock-brain

# Secrets — generate with: openssl rand -hex 32
SECRET_KEY=<random-64-char-hex>
POSTGRES_PASSWORD=<strong-password>
KEYCLOAK_ADMIN_PASSWORD=<strong-password>

# Certbot email (for Let's Encrypt expiry notices)
CERTBOT_EMAIL=you@yourdomain.com
```

Also update **`infra/digitalocean/nginx/nginx.conf`** — replace every occurrence of `yourdomain.com` with your actual domain:

```bash
sed -i 's/yourdomain.com/yourdomain.com/g' \
  /opt/bedrock-brain/infra/digitalocean/nginx/nginx.conf
```

---

## Step 6 — First deploy (get SSL certs + start stack)

```bash
ssh deploy@<droplet-ip>
cd /opt/bedrock-brain
bash infra/digitalocean/deploy.sh --first-run
```

This will:
1. Build all Docker images
2. Start nginx (HTTP only) to pass the ACME challenge
3. Issue Let's Encrypt certs for all four subdomains
4. Restart nginx with HTTPS
5. Bring up the full stack
6. Run database migrations

---

## Step 7 — Verify

| URL | Expected |
|-----|----------|
| `https://app.yourdomain.com` | React UI loads, redirects to Keycloak login |
| `https://api.yourdomain.com/healthz` | `{"status": "ok"}` |
| `https://api.yourdomain.com/docs` | FastAPI Swagger UI |
| `https://auth.yourdomain.com/admin` | Keycloak admin (admin / your password) |
| `https://mcp.yourdomain.com` | MCP Gateway 200 |

---

## Routine updates

Pull latest code and restart with zero-downtime rolling restart:

```bash
ssh deploy@<droplet-ip>
cd /opt/bedrock-brain
bash infra/digitalocean/deploy.sh
```

Or, if CI auto-deploy is wired up (see CI section), every push to `main` triggers this automatically.

---

## Useful commands on the Droplet

```bash
cd /opt/bedrock-brain

# View all service logs
docker compose -f docker-compose.yml -f infra/digitalocean/docker-compose.prod.yml logs -f

# View a specific service
docker compose ... logs brain-api --tail=100

# Open a shell in brain-api
docker compose ... exec brain-api bash

# Run DB migrations manually
docker compose ... exec brain-api alembic upgrade head

# Renew SSL certs manually (auto-renews via certbot container)
docker compose ... exec certbot certbot renew
```

---

## Cost estimate (MVP)

| Resource             | Monthly cost |
|----------------------|-------------|
| Droplet (4GB/2vCPU)  | ~$24         |
| DO Spaces (250 GB)   | ~$5          |
| **Total**            | **~$29/mo**  |

When you're ready to scale, migrate Postgres to a DO Managed Database cluster and add more Droplets behind a DO Load Balancer — or migrate the whole stack to NKP with the existing Helm charts.
