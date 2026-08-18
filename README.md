# FOCUS

**F**ollow-ups, **O**bstacles, **C**ommitments &amp; **U**pdates on **S**tatus — a
lightweight team tracker for the weekly team call. Everyone can see, at a
glance, what's planned for the next week or two and what commitments are
outstanding between teammates.

Replaces "email me what you did last week" with a living dashboard of:

- **Tasks** — work a person plans to accomplish over the next week or two.
  Stays on the dashboard until marked completed.
- **Action Items** — something one person needs another person (or
  themselves) to do. Can be assigned to anyone on the team.

Both have a running, dated/attributed **notes log** (add a comment on the
weekly call) and an **in-progress / completed** indicator.

## Dashboard

The home page shows two sections — Tasks and Action Items — with every open
record and its owner's/assignee's email. Filter by status (open / completed /
all) and by person, so anyone can filter down to just their own items for a
laser-focused view during the call. Each row has a quick "mark complete /
reopen" button plus a link to a full edit page (title/description, and the
notes log). Tasks are a personal to-do list: only the owner can edit,
add a note, toggle status, or delete a task — everyone else only sees it on
the dashboard for visibility, with no edit access at all (not even managers
or admins). Action items can be assigned to anyone (including yourself), and
managers/admins can edit or reassign those.

Action items also get a **"review" pill**: editing the item or adding a note
flips it from "in progress" to "review", so the assignee notices something
changed since they last looked. It flips back to "in progress" automatically
the next time the assignee opens the item — no separate "mark as read" step.
Marking the item complete also clears it.

Each row also has a small ✉ icon — click it to email the record's owner (task)
or assignee (action item) directly from the dashboard. A modal opens with the
recipient pre-filled (editable, but restricted to a known active user's
address), a subject automatically set from the record's type and number (e.g.
"Task #12: ..." / "Action Item #5: ..."), and a free-text note field. Sending
uses the same SMTP forwarder configured in Admin → Mail forwarder.

## Messages

Every user has their own **My Messages** queue at the top of the dashboard —
only messages addressed to them are shown. Each task/action item row has a
💬 icon (next to ✉) for sending a short, in-app ping (up to 250 characters)
to that record's owner/assignee — no email involved, and the recipient is
always locked to that record's owner/assignee (not user-selectable). Each
message shows the sender, timestamp, and a link back to the task/action item
it was about.

Each message has two actions: **↩ Reply** sends a new message straight back
to whoever sent the original (carrying the same task/action item context),
so a conversation can go back and forth between two people until either side
clears it. **× Clear** (with a confirmation prompt, so an accidental click
can't silently delete a message) permanently removes it from just that
person's own queue — it isn't a shared/persistent inbox, and clearing your
copy doesn't affect the other person's copy of a reply.

## HOLO single sign-on

If `SSO_SHARED_SECRET` is set, a **HOLO** button appears in the nav (opens in
a new tab). Clicking it generates a short-lived (60s), signed token
containing just the current user's email, and redirects to HOLO's
`/sso/focus` route — HOLO independently verifies the signature and logs the
person in if a HOLO account with that same email exists, with no separate
login step. No account auto-creation: if there's no matching HOLO account,
they land on HOLO's login page with a clear message instead.

This requires `SSO_SHARED_SECRET` to be set to the **exact same value** in
both apps' `.env` files — it's a secret shared between the two apps, not
either app's own `FOCUS_SECRET_KEY`/`HOLO_SECRET_KEY` (which sign session
cookies, not this hand-off). `HOLO_BASE_URL` must be a URL your browser can
actually reach (not necessarily what the FOCUS container itself would use) —
in production this is likely the edge-facing hostname on HOLO's port/path,
not `localhost`. If `SSO_SHARED_SECRET` is empty, the button is hidden and
`/go/holo` just bounces back to the FOCUS dashboard.

## Executive snapshot

`/metrics` gives leadership a one-page view:

- Open vs. completed counts (tasks and action items, separately)
- **Application usage by user** — a 3D-styled bar chart of audit-log activity
  (logins, task & action item changes) per person over a selectable window
  (7/30/90 days). Bar height and color intensity both scale with activity, so
  the most engaged user visually pops against everyone else — a quick read on
  who is (and isn't) actively using the system.
- Per-person open workload
- Stale items — open longer than `FOCUS_STALE_WEEKS` (default 2) without an
  update, flagged as likely obstacles
- Completion trend over the last 8 weeks
- The oldest open items across both lists

## Roles & permissions

| Role      | Can do |
|-----------|--------|
| `member`  | Create tasks for themselves only (never reassignable, and only the owner can edit/note/delete/toggle status — visible to others but locked); create action items assigned to anyone. Edit action items they requested or are assigned. |
| `manager` | Everything a member can, plus edit or reassign **any** action item (team-lead oversight), plus the full admin console (users, invites, backups). Tasks stay locked to their owner even for managers/admins. |
| `admin`   | Same access as manager. Intended for whoever owns the deployment. |

## User management & invitations

The admin console (`/admin`, admin/manager only) works like HOLO:

- **Invite a user** — generates a single-use, expiring registration link.
  Copy/paste it or email it directly via the configured SMTP forwarder.
- **Users** — change role, reset password (temporary password, must change on
  next login), enable/disable, or delete (blocked while the user still owns
  open tasks/action items — reassign or complete those first, or disable the
  account instead).
- **System log** — every state-changing action (logins, task/action item
  changes, admin actions), filterable.

## Database backup & restore

- Automatic daily backup (SQLite online-backup API — safe on a live DB),
  30-day retention, stored on the mounted volume.
- **Back up now** from the admin console; **download** any backup.
- **Restore** from an existing backup or an uploaded `.db` file. The upload is
  validated (integrity check + expected tables) before anything changes, and a
  safety snapshot of the current DB is always taken first.

## Local development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt

export FOCUS_SECRET_KEY=dev-secret
export FOCUS_COOKIE_SECURE=0   # allow plain-HTTP locally
export FOCUS_DB_PATH=./focus.db

uvicorn app.main:app --reload --port 9094
```

Sign in with the seeded default admin (`admin` / `admin`) or manager
(`manager` / `manager`) — you'll be forced to change the password on first
login. Create additional admins directly in the DB with:

```bash
python -m scripts.create_admin --email you@hpe.com --password 'secret123'
```

Run tests / lint:

```bash
pytest
ruff check .
```

## Docker (host networking)

This app is designed to run in Docker with **host networking**
(`network_mode: host`), matching the sibling apps in this deployment. In host
mode `ports:` is ignored — the app binds the host port directly (default
`9094`, override with `FOCUS_PORT`).

```bash
cp .env.example .env   # edit FOCUS_SECRET_KEY, DNS resolvers, etc.
docker compose up -d --build
```

On macOS, Docker Desktop's host networking isn't reachable from the Mac host
the way it is on Linux — `docker-compose.override.yaml` (gitignored, present
locally) switches to bridge networking with a published port for local runs
only. Production (a Linux host) keeps `docker-compose.yaml`'s host networking
unmodified.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `FOCUS_SECRET_KEY` | *(required)* | Session signing key — must be fixed so sessions survive restarts. |
| `FOCUS_DB_PATH` | `/data/focus.db` | SQLite database path. |
| `FOCUS_BACKUP_DIR` | alongside the DB | Where daily backups are written. |
| `FOCUS_BACKUP_KEEP` | `30` | Backups retained before pruning. |
| `FOCUS_ROOT_PATH` | *(empty)* | Subpath if served behind a reverse proxy/edge, e.g. `/focus`. |
| `FOCUS_COOKIE_SECURE` | `1` | Set `0` only for plain-HTTP local dev. |
| `FOCUS_COOKIE_NAME` | `focus_session` | Session cookie name. |
| `FOCUS_INVITE_TTL_DAYS` | `7` | How long an invite link stays valid. |
| `FOCUS_ADMIN_USERNAME` / `FOCUS_ADMIN_PASSWORD` | `admin` / `admin` | Seeded default admin (fresh DB only; must change password on first login). |
| `FOCUS_MANAGER_USERNAME` / `FOCUS_MANAGER_PASSWORD` | `manager` / `manager` | Seeded default manager (fills in even if the DB already has other users, as long as no manager exists yet; must change password on first login). |
| `FOCUS_STALE_WEEKS` | `2` | Weeks with no update before an open item is flagged "stale" on the metrics page. |
| `FOCUS_PORT` | `9094` | Host port (host networking). |
| `FOCUS_DNS1` / `FOCUS_DNS2` | `8.8.8.8` / `8.8.4.4` | DNS resolvers for the container (needed for the SMTP forwarder in host-networking mode). |
| `SSO_SHARED_SECRET` | *(empty — SSO disabled)* | Enables the HOLO SSO hand-off; must match HOLO's own `SSO_SHARED_SECRET` exactly. |
| `HOLO_BASE_URL` | `http://localhost:9093` | Browser-reachable URL for HOLO — override for production (edge hostname/path, not the container's own view of "localhost"). |

## Stack

FastAPI + Jinja2 + SQLAlchemy + SQLite. Passwords hashed with bcrypt; sessions
are signed cookies (Starlette `SessionMiddleware`). Single-container
deployment; no external services required (email is optional, via an
unauthenticated SMTP forwarder for invitations).
