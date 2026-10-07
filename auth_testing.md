# Authentication regression checklist
- Use the existing cached test-token helper and credentials in memory/test_credentials.md.
- Verify bcrypt hashes and unique email index; never print hashes or tokens.
- Test login, /auth/me, logout revocation, expired tokens and password-change revocation.
- In an isolated database, verify zero-page users cannot read products or mutate stores/scheduler/import/matches.
- Verify page readers can read only their allowed API families and cannot perform administrative mutations.
- Verify public registration is disabled by default and crawler/cron endpoints require separate secrets.
- Preserve production rate limits. Do not run destructive permissions tests against production.