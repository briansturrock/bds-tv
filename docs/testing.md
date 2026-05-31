# Testing checklist

## Health

```bash
curl http://127.0.0.1:8088/health
curl http://127.0.0.1:8088/api/status
```

## Docker build

```bash
docker compose up --build
```

## Image save/load

```bash
docker build -t iptv_epg:dev .
docker save iptv_epg:dev -o iptv_epg-dev-amd64.tar
docker load -i iptv_epg-dev-amd64.tar
```

## Portainer rule

Always use explicit tags, not `latest`, for deployment.
