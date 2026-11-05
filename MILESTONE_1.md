# Milestone 1 — Separate services without PostgreSQL

## Scope and completion criteria

| Requirement | Delivery |
|---|---|
| Separate frontend | Static pages in an independent Nginx container |
| Separate backend | JSON API only; no printer requests or collector threads |
| Separate collector | Independent worker with automatic polling and manual queue |
| Preserve data | Existing `./data` bind mount and JSON formats |
| Frontend collector status | Heartbeat, last poll, counts, activity, errors |
| No PostgreSQL | Local filesystem coordination only |
| Existing public address | Host reverse proxy still uses loopback port 8090 |
| Service isolation | API restart does not restart collector; no API ports published |

## Reference server migration

Do not run the old monolith and new collector against the same data directory.
Perform these steps in a maintenance window in `/opt/printer-dashboard`.
The new branch lives in Damas's repository; Aziz's `origin` and `main` are unchanged.

1. Check `git status` and preserve any local configuration/code changes before
   switching branches. Do not reset or overwrite server-specific settings.
2. Stop the old app and make a consistent backup before checkout:

   ```sh
   docker compose down
   mkdir -p /opt/printer-dashboard-backups
   tar -czf /opt/printer-dashboard-backups/pre-milestone1-$(date +%Y%m%d-%H%M%S).tgz data config.json docker-compose.yml
   git rev-parse HEAD
   ```

   Record the commit SHA and exact backup filename. Restrict access to backups if
   notification credentials are configured.
3. Fetch and check out the milestone branch:

   ```sh
   git fetch damas
   git switch -c milestone-1-split --track damas/milestone-1-split
   ```

   If the local branch already exists, switch to it instead. Preserve the existing
   server `config.json`; no printer/threshold changes are required for this milestone.
4. Validate and launch:

   ```sh
   docker compose config -q
   docker compose up -d --build
   docker compose ps
   docker compose logs --tail=100 frontend backend collector
   ```

The collector keeps the existing `br-printerdash` interface, so its printer firewall
rules remain relevant. The frontend/backend network is separate; a host firewall
with a forward-drop policy may need an allow rule for frontend-to-backend TCP 8080.
Restrict that rule to the new Docker network, not all forwarded traffic. External
Nginx upstream/HTTPS configuration remains as deployed.

## Server acceptance checks

- `/` and `/v1.html` open through the existing HTTPS address.
- `curl http://127.0.0.1:8090/api/health` returns backend `ok`.
- Printer cards match the original readings after the initial poll.
- Collector status shows a recent heartbeat and completed poll.
- Collect now returns queued state, then updates readings without a second worker.
- Stock can be saved, and existing stock/history remain present.
- `docker compose restart backend` does not interrupt collector logs/heartbeat.
- `docker compose stop collector`: after 90 seconds status becomes unresponsive,
  while stock and cached printer data remain available. Start collector again.
- `docker compose restart` preserves stock/history and recovers polling.

Build/startup, frontend routing, actual printer access and host firewall behaviour
must be verified on Docker. Local Python tests alone do not validate those paths.

## Rollback

```sh
docker compose down
# Replace SAVED_COMMIT with the SHA recorded before migration.
git switch --detach SAVED_COMMIT
docker compose up -d --build
```

Original JSON formats remain compatible. If files need restoring, stop services
first and restore from the recorded backup (restoration discards later edits).
Do not delete the `data` directory or use force pushes to roll back.

## Later milestones

PostgreSQL integration and schema migration, authentication/roles, email alerts,
per-endpoint polling schedules/backoff, historical reports and stock movements.
