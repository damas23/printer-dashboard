# Milestone 1 — Separate services, JSON storage, explicit environments

## Delivery

Frontend serves static files, backend serves the API, and collector polls independently.
Existing printer configuration, JSON formats, stock/history and poll interval are retained.
No PostgreSQL, email, login or new reporting functionality is added.

| Environment | Services | Entry point |
|---|---|---|
| Development | nginx, frontend, backend, collector | http://localhost:8090 |
| Production | frontend, backend, collector | Existing shared HTTPS Nginx |

Use `compose.yml` together with `compose.dev.yml` OR `compose.prod.yml` explicitly.
The old docker-compose.yml is removed. See [deploy/README.md](deploy/README.md).

## Production migration

Run from `/opt/printer-dashboard` during a maintenance window. Stop the old stack
BEFORE pulling/checking out the new files. Preserve uncommitted server-specific
configuration and local override files; never reset or overwrite them blindly.

1. Inspect `git status` and record `git rev-parse HEAD` and the current branch.
   Back up `/opt/nginx/nginx.conf` using your normal configuration backup location.
2. Stop the old stack using the same old Compose files that launched it. For the
   original monolith or default four-container stack:

   ```sh
   docker compose -f docker-compose.yml down
   mkdir -p /opt/printer-dashboard-backups
   tar -czf /opt/printer-dashboard-backups/pre-milestone1-$(date +%Y%m%d-%H%M%S).tgz data config.json docker-compose.yml
   ```

   Include any additional active override files in the backup. Record the archive
   path and commit SHA. Keep backups containing credentials access-restricted.
3. Update the milestone branch from Damas's remote:

   ```sh
   git fetch damas
   git switch milestone-1-split
   git pull --ff-only damas milestone-1-split
   ```

   If no local milestone branch exists, create it with
   `git switch -c milestone-1-split --track damas/milestone-1-split` instead.
   Resolve local modifications first; preserve the production config.json/data.
4. Confirm host TCP ports 8090 and 8092 are available. If 8092 is occupied, set
   PRINTER_API_PORT to an available port in an untracked .env and match the proxy
   upstream. Use the same value for later deployments.
5. Validate and start the three production services:

   ```sh
   docker compose -f compose.yml -f compose.prod.yml config -q
   docker compose -f compose.yml -f compose.prod.yml up -d --build
   docker compose -f compose.yml -f compose.prod.yml ps
   docker compose -f compose.yml -f compose.prod.yml logs --tail=100 frontend backend collector
   ```

6. Update ONLY the dashboard vhost in the existing shared host-networked Nginx.
   Use deploy/nginx-production.example.conf: `/` -> UI 127.0.0.1:8090;
   `/api/` -> backend 127.0.0.1:8092. Retain API prefix, TLS settings, domain,
   redirects and other app vhosts. Test Nginx configuration and then reload using
   the existing proxy's own Compose deployment; see deploy/README.md.

Keep one collector active; do not run the old monolith concurrently on this data.
The production bridge remains br-printerdash. Preserve its outbound printer rules;
verify UI/API published-port traffic is permitted by the host firewall as needed.

## Acceptance checks

- `curl http://127.0.0.1:8090/` returns dashboard HTML.
- `curl http://127.0.0.1:8092/api/health` returns backend `ok`.
- The existing HTTPS domain serves both dashboard themes and `/api/health`.
- `/api/state`, `/api/collector` and stock saving work through HTTPS.
- Collector heartbeat and completed poll are recent; readings match the printer.
- Collect now queues then completes without starting a second poller.
- Restarting backend leaves collector running; saved stock/history remain present.
- Stopping collector for over 90 seconds shows unresponsive status while saved
  data remains readable; starting it again recovers collection.
- Other applications behind the shared Nginx remain accessible after reload.

Python integration tests validate API/worker behaviour with a fake printer.
Docker builds, Nginx routing, file mounts, firewall and live device access must be
checked on the deployment host. A healthy static frontend alone does not validate API routing.

## Rollback

Stop the NEW production stack with its new file selection:

```sh
docker compose -f compose.yml -f compose.prod.yml down
# Replace SAVED_COMMIT with the recorded pre-migration SHA.
git switch --detach SAVED_COMMIT
docker compose -f docker-compose.yml up -d --build
```

Use the original override file selection if the old stack required it. Restore the
previous shared Nginx configuration, test it and reload. Original JSON formats remain
compatible; restore data from the backup only if necessary, with writers stopped.
Restoring data discards subsequent edits. Do not delete data or force-push Git history.

## Later milestones

PostgreSQL migration, access control, email, collection schedules/backoff and reporting.
