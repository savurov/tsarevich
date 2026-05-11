## User

The user is non-technical.
They only know how to:

1. write prompts
2. run the app from VSCode
3. use Commit + Sync in the VSCode Git tab
   Because of this:

- do technical work yourself whenever possible
- explain changes simply and briefly

---

## Workflow

- Commit + Sync triggers automatic deployment
- the user works with local DEV

---

## Database

The project uses SQLite.

- local DB: `database.sqlite3`
- production DB: also SQLite
  This project already has a built-in migration system.
- migrations live in `migrations/`
- migrations are upgrade-only
- app startup runs pending migrations automatically in prod and dev

---

## Local SQLite

Direct local DB modification is allowed.

- file: `database.sqlite3`
  If the user asks to make themselves admin, use this as user is always alone in dev:
- `UPDATE users SET is_admin = 1;`

---

## Coding style

Prefer:

- small localized changes
- simple readable solutions
- stability over cleverness
- fewer abstractions and dependencies
  Avoid:
- large refactors
- unnecessary renaming
- architecture rewrites
- unrelated improvements
- overengineering

---

## UX and communication

After changes:

1. briefly explain what changed
2. briefly explain what to test in DEV
3. avoid unnecessary technical detail

---

## Safety

Never:

- commit secrets
- expose tokens
- hardcode private credentials
- break production
