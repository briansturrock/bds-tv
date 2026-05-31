# Commit 3: Channel selection + filtered M3U

## Goal

Add the core useful output flow:

```text
indexed source channels
→ selected channels
→ filtered.m3u
```

## New endpoints

```text
GET  /api/selected-channels
POST /api/channels/select
POST /api/groups/{group_id}/select
POST /api/m3u/generate-filtered
GET  /filtered.m3u
```

## Filtered M3U behaviour

The generated M3U keeps the original provider stream URLs.

This is intentional. The intended architecture is:

```text
Threadfin/Plex → filtered.m3u from iptv_epg → provider streams
```

The browser player/proxy feature is a convenience feature, not the default playlist output mode.

## Ordering

Filtered M3U output uses:

```sql
ORDER BY
  groups.user_order IS NULL,
  groups.user_order ASC,
  groups.provider_order ASC,
  channels.user_order IS NULL,
  channels.user_order ASC,
  channels.provider_order ASC
```

Only selected channels are included.

## Not included yet

- UI pages
- EPG source/mapping/generation
- Guide
- Browser player
