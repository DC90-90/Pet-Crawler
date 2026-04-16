# Daleel Pets (دليل بيتس) — Product Requirements Document

## Problem Statement
SaaS web application for Saudi pet store owners to track and monitor competitor stores in the Saudi pet market (Zarafa, Petsy, Panda Store, etc.). Monitors product prices, stock/quantity, best sellers, categories, discounts, and out-of-stock alerts.

## Tech Stack
- **Frontend**: React 18, Tailwind CSS, Shadcn/UI, Recharts, Zustand, react-i18next
- **Backend**: FastAPI, Motor (async MongoDB), APScheduler, slowapi, Playwright, BeautifulSoup4
- **Database**: MongoDB 7
- **Auth**: PyJWT + bcrypt, httpOnly cookies
- **Deployment**: Docker Compose, Nginx reverse proxy

## Architecture
- 3-Tier Waterfall Crawler: API JSON → Playwright XHR → HTML Parsing
- JWT auth via httpOnly cookies (SameSite=Lax)
- Rate limiting: 5/min/IP on auth endpoints (slowapi)
- Security headers: CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy

## Completed Features

### Phase 1-2: Foundation (Done)
- FastAPI + MongoDB + React project structure
- JWT authentication with httpOnly cookie storage
- Admin seed account (admin@daleelpets.com)
- 200+ product seed data with 90-day snapshot history
- Arabic/English localization (RTL support)

### Phase 3: Crawler & Analytics (Done)
- Tier 1 multi-endpoint JSON crawler for Salla stores
- APScheduler-based job system (P1: 4h, P2: 8h intervals)
- MyProductsPage dashboard with KPIs, filters, sorting
- Discounts page (top %, top SAR, timeline heatmap, aggression leaderboard)
- Price Opportunity Scanner (overpriced, quick wins, undercut analysis)
- Product detail panel with price history charts

### Phase 4: Advanced Crawling & Intelligence (Done)
- Tier 2 Playwright XHR interception crawler
- Tier 3 BeautifulSoup HTML parsing crawler
- 3-tier waterfall orchestrator with crawl logging
- Weekly Market Intelligence Digest (auto-generated Sunday 05:00 UTC)
- Saudi seasonal calendar annotations on charts
- Enhanced trending category analysis

### Code Quality (Done)
- Extracted crawlers.py for maintainability
- JWT secret generation via `secrets` module
- Migrated JWT storage from localStorage to httpOnly cookies
- Fixed React hook dependency warnings

### Deployment Readiness (Done — Feb 2026)
- Docker deployment package: Dockerfiles, docker-compose.yml, nginx.conf, .env.example
- Deployment guide for AWS Bahrain / Ubuntu VPS
- start.sh launcher script with validation
- GET /api/health endpoint (MongoDB, scheduler, Playwright, uptime)
- GET /api/health/detailed endpoint (per-store connectivity: reachable, response_time_ms, http_status, last_crawl)
- Rate limiting on auth endpoints (5/min/IP, 429 response)
- HTTP security headers middleware (CSP, nosniff, DENY, strict-origin)
- PLATFORM_SUMMARY.md — complete API/page/crawler/DB reference

## What's MOCKED
- Email alerts → logged to console (Resend not yet integrated)
- Weekly digest delivery → logged to console

## Backlog

| Priority | Feature |
|----------|---------|
| P0 | Resend email integration for alerts + digest |
| P1 | Tier 4 Crawler (buyer account layer) |
| P2 | Multi-tenant role-based access |
| P2 | Webhook notifications (Slack/Telegram) |

## Test Credentials
- Admin: admin@daleelpets.com / admin123
- Auth: POST /api/auth/login
