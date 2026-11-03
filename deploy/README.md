# Server deployment

Reference deployment for the application server (`10.1.99.251`). The app runs in
Docker and is published through the shared nginx reverse proxy at `/opt/nginx`.

## Layout on the server

| Item | Path |
| --- | --- |
| Project / compose | `/opt/printer-dashboard` |
| Runtime data (volume) | `/opt/printer-dashboard/data` |
| Shared reverse proxy | `/opt/nginx` (nginx container, host networking) |
| Firewall | `/etc/nftables.conf` |

## 1. Run the container

```sh
cd /opt/printer-dashboard
git pull --ff-only
docker compose up -d --build
docker compose ps
```

The app listens on `8080` inside the container and is published on
`127.0.0.1:8090` on the host (loopback only). See `../docker-compose.yml`.

## 2. Firewall

The host's `forward` chain policy is `drop`, so the container needs an explicit
allowance to reach the printers (TCP/80). Add the rules from
[`nftables-printer-dashboard.nft`](nftables-printer-dashboard.nft) to the
`forward` chain in `/etc/nftables.conf`, then:

```sh
cp -a /etc/nftables.conf /etc/nftables.conf.bak-$(date +%Y%m%d-%H%M%S)
nft -c -f /etc/nftables.conf && nft -f /etc/nftables.conf
nft list chain inet filter forward
```

## 3. Reverse proxy (HTTPS)

Add the `upstream printer_dashboard` block and the two `server` blocks from
[`nginx-printer-dashboard.conf`](nginx-printer-dashboard.conf) to
`/opt/nginx/nginx.conf`, then:

```sh
cd /opt/nginx
docker compose exec -T nginx nginx -t
docker compose exec -T nginx nginx -s reload
```

The shared certificate (`/opt/nginx/certs/tls.crt`) is self-signed and must
include `printer-dashboard.irt.co.id` in its SANs. To regenerate it with the
extra name:

```sh
openssl req -x509 -newkey rsa:2048 -sha256 -days 800 -nodes \
    -keyout /opt/nginx/certs/tls.key -out /opt/nginx/certs/tls.crt \
    -subj "/C=ID/O=Indo Raya Tenaga/CN=asset-it.irt.co.id" \
    -addext "subjectAltName=DNS:asset-it.irt.co.id,DNS:ntp-so.irt.co.id,DNS:printer-dashboard.irt.co.id,IP:10.1.99.251,IP:127.0.0.1" \
    -addext "basicConstraints=critical,CA:FALSE" \
    -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth"
chown root:root /opt/nginx/certs/tls.crt /opt/nginx/certs/tls.key
chmod 640 /opt/nginx/certs/tls.crt /opt/nginx/certs/tls.key
cd /opt/nginx && docker compose exec -T nginx nginx -s reload
```

## 4. DNS

Point `printer-dashboard.irt.co.id` at `10.1.99.251` in internal DNS. Until then,
test from the server with `--resolve`:

```sh
curl -sI --resolve printer-dashboard.irt.co.id:80:127.0.0.1 \
  http://printer-dashboard.irt.co.id/ | grep -i '^location'   # expect 308 -> https

curl --fail --insecure --resolve printer-dashboard.irt.co.id:443:127.0.0.1 \
  https://printer-dashboard.irt.co.id/api/state
```

## Update / rollback

```sh
cd /opt/printer-dashboard
git pull --ff-only
docker compose up -d --build       # update

docker compose down                # remove the container (data in ./data is kept)
```
