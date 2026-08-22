# let’s go! architecture

The project keeps Telegram delivery, product rules, persistence, and the Mini App
separate so a new feature does not require changing unrelated code.

## Modules

- main.py — Telegram chat handlers and process startup.
- miniapp.py — authenticated HTTP handlers only.
- miniapp_routes.py — the public HTTP contract, grouped by product area.
- domain.py — shared validation, limits, and product constants.
- photo_storage.py — file storage behind a small replaceable boundary.
- miniapp_dashboard.py — the read model for the complete Mini App screen.
- reminders.py — reminder copy and delivery loop without global state.
- database.py — SQLite persistence.
- migrations.py — ordered, idempotent schema evolution with an audit trail.
- miniapp.html — the dependency-free Telegram Mini App client.

## Adding a feature

1. Put reusable rules and limits in domain.py.
2. Add the persistence operation and migration in database.py.
3. Add a small HTTP handler in miniapp.py and register it in miniapp_routes.py.
4. Add the client interaction in miniapp.html.
5. Cover the rule with a database or HTTP flow test.

HTTP handlers must validate identity and company membership before mutations.
Uploaded files must go through PhotoStorage, so object storage can replace local
files later without changing activity handlers.

SQLite runs in WAL mode with a bounded busy timeout. This allows the Telegram
poller and Mini App requests to read and write concurrently without immediately
failing on a short-lived lock.
