## Who you are working with

You are working with a NON-programmer user.

The user does NOT understand:

- git
- python
- docker
- terminals
- databases
- project architecture

The user only knows how to:

1. write prompts to you
2. run the application from VSCode
3. use Commit + Sync in the VSCode Git tab

Because of this:

- never ask the user to perform complicated technical actions
- avoid terminal commands unless absolutely necessary
- make changes yourself whenever possible
- explain things in very simple language
- after changes, briefly explain what was changed

---

# Project workflow

## Deploy

- The repository already has CI/CD connected
- After Commit + Sync, changes are automatically deployed to production
- Deployment usually takes around 1 minute

## Environments

There are two environments:

- local DEV bot
- production bot

The user works only with the local DEV version.

---

# Database

## Important

The project uses SQLite:

- local database: `database.sqlite3`
- production database: also SQLite

### CRITICAL RULE

This project has NO migration system.

Do NOT introduce:

- alembic
- sqlalchemy migrations
- prisma migrate
- django migrations
- goose
- or any migration framework

Database migrations are handled manually by the project owner.

---

# Database rules

## Forbidden

Do NOT:

- break existing database schemas
- rename existing columns
- remove existing columns
- change existing column types
- perform destructive migrations

## Allowed

You MAY:

- create NEW tables
- create NEW columns only if absolutely necessary
- use:
  - `CREATE TABLE IF NOT EXISTS`
  - `CREATE INDEX IF NOT EXISTS`
  - safe idempotent SQL operations

## Initialization

Any SQL/database setup code must:

- safely run on every application startup
- never fail if objects already exist
- remain backward compatible with existing databases

---

# Working with local SQLite

You are allowed to directly modify the local database:

- file: `database.sqlite3`

If user-related local data needs to be changed, do it yourself.

Main testing user:

- telegram_user_id = `342648746`

Examples:

- add balance
- reset state
- change subscription
- enable feature flags
- clean test data
- create testing records

Direct SQLite modification is allowed for local development.

---

# Development style

## Keep changes minimal

Prefer:

- small changes
- localized fixes
- minimal diffs

Do NOT perform:

- large refactors
- unnecessary renaming
- architecture rewrites
- unrelated "improvements"

---

# UI / UX

The user is non-technical.

Because of this:

- errors should be human-readable
- texts should be simple and clear
- if something fails, explain it in normal language

---

# After completing tasks

After making changes:

1. briefly explain what changed
2. explain what should be tested in the DEV version
3. avoid unnecessary technical details

---

# Git workflow

The user performs commits using the VSCode Git UI.

Never:

- explain advanced git workflows
- ask for rebase/cherry-pick/reset
- require terminal git commands

If needed:

- simply say: "Do Commit + Sync"

---

# Preferred engineering style

Prefer:

- simple solutions
- stability
- readable code
- fewer abstractions
- fewer dependencies

Avoid:

- overengineering
- unnecessary complexity
- abstractions for abstraction’s sake

---

# If a task requires dangerous DB changes

If a feature requires:

- destructive database changes
- column removals
- type changes
- complex data migrations

Then:

- DO NOT implement it automatically
- leave a comment/note for the project owner
- explain what must be done manually

---

# Security

Never:

- commit secrets
- expose tokens
- hardcode private credentials
- remove user data unnecessarily

---

# Priorities

Priority order:

1. Do not break production
2. Do not break SQLite databases
3. Keep things simple for the user
4. Keep changes minimal
5. Keep deployments fast
