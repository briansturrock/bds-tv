# Roadmap

## 0.8-db-foundation

- Create SQLite DB automatically on startup.
- Move durable state to SQLite.
- Keep generated/transient files on disk.
- Keep UI as thin API client.
- Do not add group-ordering UI until DB/API foundation is stable.

## 0.8.1-ui-safe

- Channels tab uses paged/scoped API data.
- EPG management page uses server-side search for XMLTV channels.
- Guide page loads one group/time-window at a time.
- No heavy work on startup.

## 0.8.2-group-order

- Add manual group ordering from Channels tab.
- Save `groups.user_order`.
- Apply same order to filtered M3U and Guide.

## Later

- Channel ordering
- Better EPG matching suggestions
- Player polish
- Optional proxied M3U mode
