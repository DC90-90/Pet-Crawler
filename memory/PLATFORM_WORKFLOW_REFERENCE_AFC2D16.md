# General platform workflow reference — not production-state evidence

**Assessment warning:** The general guidance below is reproduced verbatim for transparency. It is **not** the approved Daleel runbook and does not establish this app's capabilities, current deployment, backups or recovery time.

For this assessed commit, the scheduler statement below is contradicted by `.emergent/crons.yml` and `server.py:1739–1740,11615–11648`: this release intends **platform-managed cron dispatch**, not in-process schedules. The platform cron contract supports `enabled: false` and synchronizes schedules at deployment; the production application of that configuration remains unverified. The reported15 production in-process jobs require reconciliation before release.

Do not rely on the stated retained-version count, timing, zero-downtime behavior, backup policy or UI labels without confirming them for the actual deployment. No backup identifier or restore rehearsal was supplied. The signed go/no-go and maintenance-aware procedure are in `PRODUCTION_READINESS_AFC2D16.md` and `DEPLOYMENT_ROLLBACK_RUNBOOK_AFC2D16.md`.

---

## Production Deployment & Rollback Workflow on Emergent

Based on your read-only assessment request, here is the platform workflow guidance for future deployment and rollback operations on Emergent-hosted Daleel:

### Deployment Workflow

**Selecting a Release Version:**
1. Open the **Manage Publishes** panel from the deployed app
2. Review code changes in the preview environment before deploying
3. Click **Republish** to push preview code to production
4. Deployment takes **10-15 minutes** for a full build
5. The platform performs 8 pipeline steps: build → mongodb_migrate → manage_secrets → deploy → transfer_files → health_check → switch_traffic → cleanup

**Version Identification:**
- Each deployment is recorded in the **Overview tab** with timestamp, deployment ID, and commit hash
- Up to **3 recent successful deployments** are retained and eligible for rollback
- The **Deployments** section shows all deployed versions with **View Logs** links

### Rollback Workflow

**Supported Rollback:**
1. Navigate to **Manage Publishes → Overview tab**
2. Click the **rollback icon (↺)** on a previous deployment version
3. Confirm in the **Confirm Rollback** modal
4. Rollback completes in **1-3 minutes** (reuses existing Docker image, skips build)
5. Zero downtime during rollback
6. Live URL instantly serves the older version

**Important Limitations:**
- Only the **last 3 successful deployments** can be rolled back
- Rollback reverts **code/container image only**
- **Database data is NOT rolled back** - MongoDB production data remains at current state
- **Secrets/environment variables** are NOT rolled back - current values persist
- **MongoDB indexes** created after the rollback point remain in place
- **External storage** (if any) is NOT affected by code rollback

### What Rollback Does NOT Cover

**Database & Data:**
- No automatic database snapshot/restore capability is documented
- No Point-in-Time Recovery (PITR) for application databases is mentioned for user-initiated rollback
- Production MongoDB has automated cloud backups (hourly/daily/weekly/monthly/yearly retention per the backup policy), but user-triggered restore workflow is not documented in the KB
- Preview and production databases are completely independent after first deploy

**Scheduled Jobs:**
- Cron jobs/scheduled tasks run in-process within the application container
- No separate job scheduler pause/resume controls are documented
- Rolling back code will revert job definitions, but any jobs that executed between versions cannot be undone
- For Starter/Launch tier: apps scale to zero during inactivity, which stops in-process schedulers

**Secrets & Configuration:**
- Environment variables/secrets are managed separately in **Manage Publishes → Secrets tab**
- Changes to secrets require manual edit + redeploy to take effect
- Rollback does not revert secret values to their state at that deployment time

### Capabilities Requiring Confirmation

The following are **NOT documented** in the Knowledge Base and should be confirmed with Emergent support before assuming availability:

- **Traffic canary/gradual rollout** - no evidence of percentage-based traffic splitting
- **Version pinning** - no documented ability to pin/lock a specific version
- **Database snapshot/PITR for rollback** - backup policy exists but user-triggered restore workflow not documented
- **Scheduled task pause controls** - no separate scheduler management interface documented

### Health & Monitoring

- **App Analytics** available (Pro users) - shows traffic, users, visit duration
- **App Observability** (gated feature) - hourly health status, request latency, CPU/memory usage
- Health checks run continuously; apps must respond to `/health` (backend) or return HTTP 200 at root (frontend)
- Deployment failures trigger **Cortex auto-recovery** (up to 2 automatic retry attempts)

### Best Practice Recommendations

1. **Test thoroughly in preview** before each production deployment
2. **Export to GitHub** between major feature additions to preserve working versions
3. **Document the last known-good deployment ID** before each new deployment
4. **Verify health checks pass** after deployment before considering it stable
5. **Understand that rollback is code-only** - plan data migrations carefully as they cannot be automatically reverted

---

**Note:** This guidance is based on documented Emergent platform capabilities. For production-critical operations, confirm current platform behavior with Emergent support at support@emergent.sh, especially regarding database restore procedures and any undocumented rollback limitations specific to your deployment tier and configuration.