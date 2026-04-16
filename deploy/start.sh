#!/bin/bash
##############################################
# Daleel Pets — Quick Start Script
# Usage: chmod +x start.sh && ./start.sh
##############################################
set -e

COMPOSE_FILE="docker-compose.yml"
ENV_FILE="../.env"

echo "============================================"
echo "  Daleel Pets — دليل بيتس"
echo "  Deployment Launcher"
echo "============================================"

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker not installed. Run: curl -fsSL https://get.docker.com | sudo sh"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: Docker Compose v2 not found. Run: sudo apt install docker-compose-plugin"; exit 1; }

# Check .env
if [ ! -f "$ENV_FILE" ]; then
    echo ""
    echo "No .env file found at project root."
    echo "Creating from template..."
    cp .env.example "$ENV_FILE"
    echo ""
    echo "IMPORTANT: Edit $ENV_FILE before continuing:"
    echo "  1. Set JWT_SECRET (run: python3 -c \"import secrets; print(secrets.token_hex(64))\")"
    echo "  2. Set ADMIN_PASSWORD to a strong password"
    echo "  3. Set CORS_ORIGINS to your domain (e.g. https://daleel.example.com)"
    echo "  4. Set REACT_APP_BACKEND_URL to your domain"
    echo ""
    echo "Then re-run: ./start.sh"
    exit 1
fi

# Validate critical env vars
source "$ENV_FILE"
if [[ "$JWT_SECRET" == *"CHANGE_ME"* ]]; then
    echo "ERROR: JWT_SECRET is still the placeholder. Generate one:"
    echo "  python3 -c \"import secrets; print(secrets.token_hex(64))\""
    exit 1
fi
if [[ "$ADMIN_PASSWORD" == *"CHANGE_ME"* ]]; then
    echo "ERROR: ADMIN_PASSWORD is still the placeholder. Set a strong password in .env"
    exit 1
fi

echo ""
echo "Building and starting all services..."
echo "  (First build takes 5-10 minutes for Playwright/Chromium)"
echo ""

docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --build

echo ""
echo "Waiting for services to become healthy..."
sleep 10

# Health check loop
MAX_WAIT=120
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    BACKEND=$(docker inspect --format='{{.State.Health.Status}}' daleel-backend 2>/dev/null || echo "starting")
    MONGO=$(docker inspect --format='{{.State.Health.Status}}' daleel-mongo 2>/dev/null || echo "starting")
    
    if [ "$BACKEND" = "healthy" ] && [ "$MONGO" = "healthy" ]; then
        break
    fi
    
    echo "  Waiting... (mongo=$MONGO, backend=$BACKEND) [${WAITED}s / ${MAX_WAIT}s]"
    sleep 5
    WAITED=$((WAITED + 5))
done

echo ""
echo "============================================"
echo "  Service Status"
echo "============================================"
docker compose -f "$COMPOSE_FILE" ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "Quick verification:"
echo "---"
API_RESPONSE=$(curl -sf http://localhost/api/ 2>/dev/null || echo "FAILED")
echo "  API:  $API_RESPONSE"
HEALTH_RESPONSE=$(curl -sf http://localhost/api/health 2>/dev/null || echo "FAILED")
echo "  Health: $HEALTH_RESPONSE"
echo "---"
echo ""

if [ "$API_RESPONSE" != "FAILED" ]; then
    echo "Daleel Pets is RUNNING!"
    echo ""
    echo "Next steps:"
    echo "  1. Open http://YOUR_SERVER_IP in browser"
    echo "  2. Login with admin@daleelpets.com"
    echo "  3. Set up SSL: see DEPLOYMENT_GUIDE.md Step 4"
    echo "  4. Trigger a test crawl from the Store Registry page"
else
    echo "WARNING: API not responding. Check logs:"
    echo "  docker compose -f $COMPOSE_FILE logs -f"
fi
echo ""
