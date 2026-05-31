# Patch: Fix FastAPI response annotations

This patch fixes the startup crash caused by FastAPI trying to treat response union type annotations as Pydantic response models.

The issue looked like:

```text
FastAPIError: Invalid args for response field!
FileResponse | PlainTextResponse is not a valid Pydantic field type
```

## Fix

Generated file endpoints now use:

```python
@app.get("/filtered.m3u", response_model=None)
def filtered_m3u() -> Response:
```

and:

```python
@app.get("/filtered_epg.xml", response_model=None)
def filtered_epg() -> Response:
```

## Apply

From the repo root:

```bash
unzip iptv_epg_patch_fastapi_response_annotations.zip -d /tmp/iptv_epg_patch
cp -R /tmp/iptv_epg_patch/* .
git add .
git commit -m "Fix FastAPI response annotations"
git push
```

## Test

```bash
sudo docker compose up --build -d
curl http://127.0.0.1:8088/health
curl http://127.0.0.1:8088/api/status
```
