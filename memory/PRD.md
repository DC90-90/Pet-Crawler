# PetTracker - KSA Competitor Monitoring Tool

## Problem Statement
Build a competitor tracking and monitoring tool for the Pets & Supplies market in Saudi Arabia. Track competitors (Zarafa, Petsy, Aleef, Lanapets, Petshouses) with the ability to add new ones. Monitor product prices, stock, best sellers, categories, discounts, reviews, ratings, shipping. Simple tables with filtering/sorting. Real-time sync with stores (Salla, Zid, Shopify).

## Architecture
- **Backend**: FastAPI + MongoDB (Motor async driver)
- **Frontend**: React + Tailwind CSS + Shadcn UI
- **Database**: MongoDB (competitors, products collections)
- **Design**: Swiss & High-Contrast light theme (Work Sans + IBM Plex Sans)

## User Personas
- **Business Owner**: Tracks competitors to understand pricing and market trends
- **Market Analyst**: Monitors best sellers, price comparisons, stock levels

## Core Requirements
- Dashboard with market overview metrics
- Competitor CRUD management with sync status
- Product tracking with filtering/sorting (category, competitor, stock, search)
- Best sellers ranking
- Cross-competitor price comparison matrix
- Store sync simulation (Salla, Zid, Shopify)

## What's Been Implemented (April 15, 2026)
- Full backend API: 13+ endpoints for competitors, products, dashboard, sync
- Seeded 5 competitors with 110 products across 8 categories
- Dashboard page with 8 metric cards + category/competitor breakdowns
- Competitors management page with add/edit/delete/sync
- Products table with multi-filter + multi-sort
- Best Sellers ranking page with category filter
- Price Comparison matrix with spread indicators
- Sidebar navigation

## Prioritized Backlog
### P0 (Critical)
- [x] Core dashboard with metrics
- [x] Competitor CRUD
- [x] Product tracking table with filters
- [x] Best sellers view
- [x] Price comparison matrix

### P1 (Important)
- [ ] Real store API integration (Salla, Zid, Shopify APIs)
- [ ] Historical price tracking and trend charts
- [ ] Export data to CSV/Excel

### P2 (Nice to Have)
- [ ] Email alert system for price changes/stock changes
- [ ] Product detail view with price history chart
- [ ] Competitor profile pages
- [ ] Multi-language support (Arabic/English)
- [ ] Auto-discovery of new competitors

## Next Tasks
1. Integrate real store APIs (Salla, Zid, Shopify) for live data sync
2. Add historical price tracking with trend graphs
3. Export functionality (CSV/Excel)
4. Arabic language support
