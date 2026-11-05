# Deployment environments

Application code and JSON data formats are identical in both environments.
Always explicitly select the base file and exactly one environment file.

| Environment | Command files | Proxy |
|---|---|---|
| Laptop / WSL with Docker Desktop Linux containers | `compose.yml` + `compose.dev.yml` | Bundled dev Nginx on localhost:8090 |
| Production Linux | `compose.yml` + `compose.prod.yml` | Existing shared host-networked HTTPS Nginx |

## Laptop

```sh
docker compose -f compose.yml -f compose.dev.yml config -q
docker compose -f compose.yml -f compose.dev.yml up -d --build
docker compose -f compose.yml -f compose.dev.yml ps
```

Open http://localhost:8090 or http://localhost:8090/v1.html. The bundled
`nginx-dev.conf` routes `/` to frontend:80 and `/api/` to backend:8080.
No `/opt/nginx` file, DNS, TLS setup or local override is required.
Frontend/backend have no published ports in dev.

For UI-only work (no printer polling), start `frontend backend nginx` explicitly.
This does not stop a collector that is already running: stop it explicitly first.
Use VPN/LAN access for real printer data; avoid running a second collector against
production printers unintentionally. Local JSON storage is separate from server data.

The dev project name is `printer-dashboard-dev` and its printer bridge is
`br-printerdev`. Production retains project `printer-dashboard` and bridge
`br-printerdash` for the existing printer firewall rules. Do not point both projects
at the same data directory. Dev and prod still use the same port by default; if
running on the same host, choose a different PRINTER_HTTP_PORT for one environment.

## Existing laptop deployment upgrade

Before pulling this change, stop the OLD four-service stack using its old config:

```sh
docker compose -f docker-compose.yml down
```

Preserve any local overrides/configuration first. If you used overrides to create
the old stack, use the same old file selection for shutdown. Do this BEFORE pulling,
since docker-compose.yml is removed by this update. Data bind mounts are retained;
do not delete data. Then pull and use the dev commands above.

## Production

Follow [MILESTONE_1.md](../MILESTONE_1.md) for backup and migration.

```sh
docker compose -f compose.yml -f compose.prod.yml config -q
docker compose -f compose.yml -f compose.prod.yml up -d --build
docker compose -f compose.yml -f compose.prod.yml ps
```

There is no extra nginx service in production. UI is published at 127.0.0.1:8090;
API at 127.0.0.1:8092. Check 8092 is free first, or set PRINTER_API_PORT consistently
in the deployment environment/.env and Nginx upstream. The collector publishes no port.

Use `nginx-production.example.conf` to edit only the dashboard's existing vhost in
`/opt/nginx/nginx.conf`. Keep other apps, domain, TLS certificates and HTTP redirect.
Preserve the `/api/` prefix when proxying to the backend (no proxy_pass trailing slash).
The example is instructional, not a replacement for the full shared Nginx config.

Test and reload through your EXISTING Nginx stack from its own directory. Assuming
its Compose service is named nginx:

```sh
docker compose exec -T nginx nginx -t
docker compose exec -T nginx nginx -s reload
```

Reload only if the configuration test succeeds. If Nginx uses a different service
name/Compose file, use that deployment's equivalent commands. Do not restart other apps.

`nftables-printer-dashboard.nft` remains the printer bridge reference. The host firewall
must also permit the necessary published UI/API connections through the Docker bridge.
Never broadly open all forwarded traffic just to make the app work.

## Files and validation

Real credentials, certificate files and machine-specific overrides stay out of Git.
The repository includes reproducible development routing and a production example.
Store host-managed production Nginx configuration in your normal backed-up configuration
location. Docker builds, proxy routing and actual printer connectivity require acceptance
checks on a Docker host; Python integration tests do not cover these paths.
