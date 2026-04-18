# Daleel Pets (دليل بيتس) — PRD

## Original Problem Statement
SaaS web application for Saudi pet store owners to track & monitor competitor stores in the Saudi pet market (Salla, Zid platforms). Monitor product prices, stock/quantity, best sellers, categories, and discounts.

## Core Requirements
- Multi-tier crawler (Tier 1/2/3 fallback + external Saudi-IP ingest)
- Product matching engine: Barcode > SKU > Name, max 150% price diff, max 10% weight diff
- Premium Dark SaaS UI (glassmorphism, Recharts, dark-mode first, Arabic RTL, SAR ﷼)
- FastAPI + MongoDB + JWT (httpOnly cookies) + APScheduler
- External Ingest API with Bearer token auth

## What's Implemented
- Multi-tier crawler + external ingest endpoint
- Product matcher with strict rules
- Excel baseline import (MySKUwatch)
- Price Intelligence + Insights dashboards with charts
- Fernet-encrypted credentials vault
- Auto-generated price alerts from matched data
- Docker deployment package
- Premium dark UI rebrand

## Recent Fixes (Feb 2026)
- `seed_database()` now force-updates admin password hash on every startup
- `CRAWLER_TOKEN` fully hardcoded in `server.py` (no env var fallback) to prevent stale env overrides causing 401s on production
- `/api/debug/token` reports `source: "hardcoded"`

## Backlog
- **P1** Resend email integration (alerts + weekly digest)
- **P1** Multi-tenant role-based access
- **P2** Webhook notifications (Slack/Telegram)
- **Refactor** Split large pages (`PriceIntelPage.jsx`, `InsightsPage.jsx`); organize backend into `routes/` and `models/`

## Credentials
- Admin: `admin@daleelpets.com` / `BGv8ZcRYrBTPlJFHHhZQ3Q`
- Crawler token (hardcoded): `zj7n4vATDYACt-FswvDd_EITEwti5WciV2yZt3I2IgHbDi7XKP9myrd2xSFYZGjO`
