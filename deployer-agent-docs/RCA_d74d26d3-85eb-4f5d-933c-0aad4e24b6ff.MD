# Production Environment Audit — saudi-pets-monitor (daleel.hrm-sa.com)

**Mode:** read-only audit. No deploy, no changes. No secret values printed.

## Active deployment
- deployment_id: d92f6fcd-0827-4252-9842-f2112a2b0a73
- active_run_id: d74d26d3-85eb-4f5d-933c-0aad4e24b6ff (type: redeploy, status: success)
- deployed_at: 2026-10-10T14:39:52Z (run started 14:33:14Z)
- frontend_type: cloudflare, tier_2, template fastapi_react_mongo_shadcn_base_image
- custom domain: daleel.hrm-sa.com (verified)

## Tool limitation
list_secrets returns presence (set/empty) + optional matches_expected only. It NEVER returns stored values. Therefore exact literal values for section A and for DB_NAME could NOT be retrieved; only match/no-match and presence are reportable.

## A) Non-secret config (from list_secrets equals-check on active run)
- CORS_ORIGINS: SET, matches_expected=true (== https://daleel.hrm-sa.com)
- SEED_DEMO_DATA: NOT SET (absent from secret list) → no
- PROXY_ENABLED: SET, matches_expected=true (== false)
- MAX_OFFER_AGE_DAYS: NOT SET → app falls back to built-in default 7; /api/ready reports maximum_offer_age_days=7, expected 14 → no
- ALLOW_PUBLIC_REGISTRATION: NOT SET → no

## B) Secrets (presence only — all is_empty=false unless noted)
- MONGO_URL: set
- DB_NAME: set (value not retrievable)
- JWT_SECRET: set
- ENCRYPTION_KEY: set
- SUPER_ADMIN_EMAIL: set
- SUPER_ADMIN_PASSWORD: set
- ZID_API_TOKEN: set
- ZID_STORE_ID: set
- CRAWLER_TOKEN: set

## Extra flags (not requested, surfaced)
- ZID_OAUTH_TOKEN: present but is_empty=true (EMPTY)
- Separate ADMIN_EMAIL / ADMIN_PASSWORD keys exist alongside SUPER_ADMIN_* — confirm which the app reads.

## Live endpoints
- GET /api/health → 200 {status: healthy, mongodb: connected, boot.phase: ready-observer, last_successful_crawl 2026-10-09T21:00:55Z}
- GET /api/ready → 503 {ready:false, mode:"observer", price_comparison_only:true, maximum_offer_age_days:7, writer_schema.missing=[products.offer_id:unique-string-index, product_snapshots.event_id:unique-string-index], reason:"boot_or_release_identity..."}
  → consistent with the already-identified observer-mode (no-writer) cause of "no data since 9 Oct".

## Action items for the user (Deployment Panel → Secrets), before/with the code fix
1. Add SEED_DEMO_DATA=false (currently unset).
2. Add MAX_OFFER_AGE_DAYS=14 (currently unset; app running default 7).
3. Add ALLOW_PUBLIC_REGISTRATION=false (currently unset).
4. Review ZID_OAUTH_TOKEN (empty) — set if ZID OAuth is required.
5. Confirm ADMIN_* vs SUPER_ADMIN_* duplication is intended.
CORS_ORIGINS and PROXY_ENABLED already match expected.
