# Daleel Pets — Deployment Guide
# دليل نشر دليل بيتس

## Architecture

```
Client (Browser)
    │
    ▼
┌──────────────────────────────┐
│  Nginx (:80/:443)            │
│  SSL termination             │
│  Rate limiting               │
│  /api/* → backend:8001       │
│  /*     → frontend:3000      │
└──────┬────────────┬──────────┘
       │            │
       ▼            ▼
┌──────────┐  ┌──────────────┐
│ Frontend │  │   Backend    │
│ React    │  │   FastAPI    │
│ :3000    │  │   :8001      │
│ (nginx)  │  │              │
└──────────┘  │ ┌──────────┐ │
              │ │ Crawler  │ │
              │ │Playwright│→→→ Saudi Pet Stores
              │ │ (direct) │ │   (no proxy)
              │ └──────────┘ │
              │              │
              │ ┌──────────┐ │
              │ │Scheduler │ │
              │ │APScheduler│ │
              │ └──────────┘ │
              └──────┬───────┘
                     │
                     ▼
              ┌──────────────┐
              │   MongoDB    │
              │   :27017     │
              └──────────────┘
```

## Prerequisites

- Ubuntu 22.04 LTS (AWS Bahrain `me-south-1` recommended for Saudi store access)
- Minimum: 2 vCPU, 4 GB RAM, 30 GB SSD
- Recommended: 4 vCPU, 8 GB RAM, 50 GB SSD (Playwright uses ~1GB per crawl)
- Domain name pointed to server IP (A record)
- Ports 80 and 443 open in security group / firewall

## Step 1 — Server Setup

```bash
# SSH into your server
ssh ubuntu@YOUR_SERVER_IP

# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# Install Docker Compose v2
sudo apt install -y docker-compose-plugin

# Verify
docker --version        # Docker 24+
docker compose version  # Docker Compose v2+

# Logout and login to apply group
exit
ssh ubuntu@YOUR_SERVER_IP
```

## Step 2 — Clone and Configure

```bash
# Create project directory
mkdir -p ~/daleel-pets && cd ~/daleel-pets

# Copy the deployment files from this repository
# Arrange into this structure:
#
# daleel-pets/
# ├── backend/
# │   ├── server.py
# │   ├── crawlers.py
# │   ├── requirements.txt
# │   └── .env               ← created from .env.example
# ├── frontend/
# │   ├── package.json
# │   ├── yarn.lock
# │   ├── public/
# │   ├── src/
# │   └── ...
# ├── deploy/
# │   ├── docker-compose.yml
# │   ├── backend.Dockerfile
# │   ├── frontend.Dockerfile
# │   ├── nginx.conf
# │   ├── .env.example
# │   └── ssl/               ← created in Step 4
# └── .env                   ← root .env (symlink or copy)

# Generate environment file
cp deploy/.env.example .env

# Generate a strong JWT secret
python3 -c "import secrets; print(secrets.token_hex(64))"
# Copy the output and paste into .env as JWT_SECRET

# Edit .env with your values
nano .env
```

### Required .env values:

| Variable | Example | Notes |
|----------|---------|-------|
| `JWT_SECRET` | (64+ hex chars) | `python3 -c "import secrets; print(secrets.token_hex(64))"` |
| `ADMIN_PASSWORD` | `StrongP@ss2026!` | Change from default |
| `CORS_ORIGINS` | `https://daleel.example.com` | Your domain, with https |
| `REACT_APP_BACKEND_URL` | `https://daleel.example.com` | Same domain (nginx routes /api) |

## Step 3 — Build and Start

```bash
cd ~/daleel-pets

# Build all containers (first run takes 5-10 minutes)
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build

# Watch logs
docker compose -f deploy/docker-compose.yml logs -f

# Verify all containers running
docker compose -f deploy/docker-compose.yml ps

# Expected output:
# daleel-mongo     running (healthy)
# daleel-backend   running (healthy)
# daleel-frontend  running
# daleel-nginx     running (healthy)
```

### Verify services:

```bash
# Backend API
curl http://localhost:8001/api/
# → {"message":"Daleel Pets API - دليل بيتس"}

# Frontend
curl -s http://localhost:3000 | head -5
# → <!doctype html>...

# Through nginx
curl http://localhost/api/
# → {"message":"Daleel Pets API - دليل بيتس"}

# Login test
curl -s -X POST http://localhost/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@daleelpets.com","password":"YOUR_ADMIN_PASSWORD"}' | python3 -m json.tool
```

## Step 4 — SSL with Let's Encrypt

```bash
# Install certbot
sudo apt install -y certbot

# Get certificate (stop nginx temporarily)
docker compose -f deploy/docker-compose.yml stop nginx

sudo certbot certonly --standalone \
  -d daleel.example.com \
  --email your-email@example.com \
  --agree-tos --non-interactive

# Copy certs to deploy/ssl/
sudo mkdir -p ~/daleel-pets/deploy/ssl
sudo cp /etc/letsencrypt/live/daleel.example.com/fullchain.pem ~/daleel-pets/deploy/ssl/
sudo cp /etc/letsencrypt/live/daleel.example.com/privkey.pem ~/daleel-pets/deploy/ssl/
sudo chown -R $USER:$USER ~/daleel-pets/deploy/ssl/

# Edit nginx.conf:
# 1. Uncomment the return 301 line (HTTP → HTTPS redirect)
# 2. Uncomment the entire HTTPS server block
# 3. Replace 'your-domain.com' with your actual domain
nano deploy/nginx.conf

# Restart nginx
docker compose -f deploy/docker-compose.yml up -d nginx

# Verify HTTPS
curl https://daleel.example.com/api/
```

### Auto-renew SSL:

```bash
# Add cron job for auto-renewal
sudo crontab -e

# Add this line:
0 3 * * * certbot renew --quiet --deploy-hook "cp /etc/letsencrypt/live/daleel.example.com/fullchain.pem /home/ubuntu/daleel-pets/deploy/ssl/ && cp /etc/letsencrypt/live/daleel.example.com/privkey.pem /home/ubuntu/daleel-pets/deploy/ssl/ && docker restart daleel-nginx"
```

## Step 5 — Verify Crawler (Critical)

The crawler MUST run from the server's IP, not behind any CDN or proxy.

```bash
# Test Tier 1 (JSON endpoints — will likely fail with 410)
docker exec daleel-backend python3 -c "
import asyncio, httpx
async def test():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get('https://zarafaksa.com/api/v2/products?per_page=5&page=1')
        print(f'Tier 1: HTTP {r.status_code}')
asyncio.run(test())
"

# Test Tier 2 (Playwright XHR interception)
# Trigger a crawl via API
TOKEN=$(curl -s -X POST http://localhost/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@daleelpets.com","password":"YOUR_PASSWORD"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

# Get Zarafa store ID
ZARAFA_ID=$(curl -s http://localhost/api/stores \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);s=d.get('stores',d);print(next(x['id'] for x in s if x['name']=='Zarafa'))")

# Crawl
curl -s -X POST "http://localhost/api/stores/$ZARAFA_ID/crawl" \
  -H "Authorization: Bearer $TOKEN" --max-time 120 \
  | python3 -m json.tool

# Expected: tier_used=2, products_found >= 5
```

## Step 6 — MongoDB Backup

```bash
# Create backup script
cat > ~/daleel-backup.sh << 'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M)
BACKUP_DIR=~/backups/daleel
mkdir -p $BACKUP_DIR
docker exec daleel-mongo mongodump --db daleel_pets --archive=/tmp/daleel_$DATE.gz --gzip
docker cp daleel-mongo:/tmp/daleel_$DATE.gz $BACKUP_DIR/
docker exec daleel-mongo rm /tmp/daleel_$DATE.gz
# Keep last 30 days
find $BACKUP_DIR -name "daleel_*.gz" -mtime +30 -delete
echo "Backup saved: $BACKUP_DIR/daleel_$DATE.gz"
EOF
chmod +x ~/daleel-backup.sh

# Add daily cron job
crontab -e
# Add: 0 2 * * * /home/ubuntu/daleel-backup.sh >> /var/log/daleel-backup.log 2>&1

# Test backup
~/daleel-backup.sh

# Restore from backup
docker exec -i daleel-mongo mongorestore --db daleel_pets --archive --gzip < ~/backups/daleel/daleel_YYYYMMDD_HHMM.gz
```

## Operations

### View logs
```bash
docker compose -f deploy/docker-compose.yml logs -f backend    # Backend + crawler
docker compose -f deploy/docker-compose.yml logs -f mongo      # Database
docker compose -f deploy/docker-compose.yml logs -f nginx      # Web traffic
```

### Restart services
```bash
docker compose -f deploy/docker-compose.yml restart backend    # Restart backend only
docker compose -f deploy/docker-compose.yml up -d --build backend  # Rebuild + restart
docker compose -f deploy/docker-compose.yml down && docker compose -f deploy/docker-compose.yml up -d  # Full restart
```

### Update code
```bash
cd ~/daleel-pets
# Pull latest code...
docker compose -f deploy/docker-compose.yml up -d --build
```

### MongoDB shell
```bash
docker exec -it daleel-mongo mongosh daleel_pets
# > db.stores.find().pretty()
# > db.products.countDocuments()
# > db.product_snapshots.countDocuments()
# > db.crawl_logs.find().sort({completed_at: -1}).limit(5).pretty()
```

## Monitoring Checklist

| Check | Command | Expected |
|-------|---------|----------|
| All containers up | `docker compose ps` | 4 services running |
| Backend healthy | `curl localhost/api/` | JSON response |
| MongoDB connected | `docker exec daleel-mongo mongosh --eval "db.stats()"` | Connected |
| Crawler working | Check Store Registry UI | Tier 2 success |
| Scheduler running | `curl localhost/api/scheduler/status` | 7+ jobs |
| SSL valid | `curl -vI https://your-domain.com 2>&1 \| grep expire` | Not expired |
| Disk usage | `df -h` | <80% |
| Memory usage | `free -h` | <80% |

## Troubleshooting

### Crawler returns 0 products
- **Check**: Is the server in a Saudi IP range? Some stores block non-Saudi IPs
- **Fix**: Use AWS Bahrain (me-south-1) or a Saudi VPS provider
- **Verify**: `docker exec daleel-backend curl -s https://zarafaksa.com | head -20`

### Playwright fails to launch
- **Check**: `docker exec daleel-backend playwright install --with-deps chromium`
- **Check**: Memory — Playwright needs ~500MB per browser instance
- **Fix**: Ensure `--no-sandbox` flag in crawler code

### MongoDB connection refused
- **Check**: `docker compose logs mongo`
- **Fix**: Ensure mongo container is healthy before backend starts (handled by depends_on)

### CORS errors in browser
- **Check**: `.env` CORS_ORIGINS matches your exact domain (with https://)
- **Fix**: Set `CORS_ORIGINS=https://your-exact-domain.com` and rebuild backend

### SSL certificate expired
- **Fix**: `sudo certbot renew` then `docker restart daleel-nginx`

## AWS Bahrain (me-south-1) Specific Notes

1. **Enable me-south-1**: AWS Bahrain is opt-in. Go to AWS Console → Account → Regions → Enable me-south-1
2. **Instance type**: `t3.medium` (2 vCPU, 4GB) minimum for Playwright
3. **Security group**: Open ports 80, 443, 22
4. **Elastic IP**: Assign a static IP so Saudi stores see consistent requests
5. **Saudi IP advantage**: Salla and Zid stores may return different (better) responses to Saudi IPs
6. **Latency**: ~5ms to Saudi stores vs ~150ms from US/EU

## Production Hardening Checklist

- [ ] Change ADMIN_PASSWORD from default
- [ ] Generate strong JWT_SECRET (64+ chars)
- [ ] Set CORS_ORIGINS to exact production domain
- [ ] Enable HTTPS (SSL certificate)
- [ ] Uncomment HTTPS server block in nginx.conf
- [ ] Enable HTTP → HTTPS redirect in nginx.conf
- [ ] Set up automated MongoDB backups
- [ ] Set up SSL auto-renewal
- [ ] Monitor disk space (snapshots grow ~5MB/day)
- [ ] Set up log rotation for nginx
- [ ] Consider MongoDB authentication for production
- [ ] Set up monitoring (uptime, disk, memory alerts)
