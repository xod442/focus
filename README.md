# FOCUS

**F**ollow-ups, **O**bstacles, **C**ommitments &amp; **U**pdates on **S**tatus — a
lightweight team tracker for the weekly team call. Everyone can see, at a
glance, what's planned for the next week or two and what commitments are
outstanding between teammates.

Replaces "email me what you did last week" with a living dashboard of:

> **Design:** see [`DESIGN.md`](DESIGN.md) for the shared token reference and
> UI process/checklist used across opal, opal-mist, holo, focus, and vista.

- **Action Items** — a single list of commitments, including self-initiated
  work and assignments from managers or teammates.
- **Presentations** — customer, technical spotlight, and event presentations
  tracked from collaboration through development to delivery.

Action items have an owner, creator, priority, optional due date, and a dated,
attributed update log. Statuses are **Not started / In progress / Blocked / Completed**.

## Home and Work

FOCUS opens on a home page (`/`) with separate **Work** and **Presentations**
areas. Work (`/work`) contains action items and messages. Existing dashboard bookmarks with
status/person filters redirect to Work with those filters preserved.

The navigation keeps **Home**, **Work**, **Presentations**, and **Metrics** visible. Managers and admins
can find **Admin** and **System Log** under **Manage**; **Account** contains
**Change password** and **Log out**. The signed-in user's email and role remain
visible in the header, even when menus are closed. On smaller screens, use
**Menu** to expand the navigation.

**My Work** (`/work?person=me`) shows only items owned by you, not items you
requested from somebody else. **Team View** (`/work`) shows each person's active
item count, broken down by status, plus high-priority and overdue counts. Counts
are a visibility signal, not a comparison of effort or a performance score.
Inactive owners with open work remain visible.

Creating an item requires only a **title**; the owner defaults to yourself,
priority to Normal, and status to Not started. Description and due date are
optional. Start, complete, or reopen directly from a row. The detail page supports
all four statuses; marking Blocked requires a short reason. Progress notes are
optional. Status and ownership changes automatically enter the history.
Blocked and overdue work sorts ahead of other active work. Filter by owner and
status to focus the list. Creators, current owners, and managers/admins may edit
or reassign an item; other team members can view it and contribute notes.

Managers/admins can **transfer all open items** from one owner to another using
Team View's transfer panel (linked from Admin). Completed items stay put. Transfers
preserve the creator, dates, notes, and original status, and log old/new owners.
New assignments and reassignments send an in-app message to the new owner.
Disable departing users rather than deleting them to preserve attribution.

### Existing TODOs and upgrades

On startup, existing TODOs are migrated once into self-created action items,
including completed work, original dates, descriptions, and attributed notes.
Messages about TODOs are relinked to the new action item. Old detail bookmarks
redirect to the migrated record, and `/tasks/new` redirects to action-item creation.
Old TODO write endpoints return HTTP 410 so stale forms cannot create a second
work list. Original task rows are retained for recovery, but excluded from workload
and reporting. A migration marker prevents deleted migrated items from reappearing.
Existing action items keep their current status and description; their priority
defaults to Normal and their due date remains unset.

Before deploying, download a database backup from Admin. Schema additions and
data migration run automatically against the existing database volume.

Both action-item assignment forms include people with an unexpired, unused
invitation, labelled **invite pending**. Assigning work reserves an inactive
account; the invitee cannot sign in (including via SSO) until they accept an
invitation and set a password. Registration activates the same account, preserving
its assignments and messages. Expired or revoked invites cannot receive new
assignments; work already assigned remains attached to that email and can be
reassigned or claimed after a fresh invitation is accepted. Disabled registered
accounts are not eligible for new assignments.

Action items also get a separate **"review" pill** when something changes,
so the assignee notices it without replacing the workflow status.
It clears automatically the next time the assignee opens the item — no separate "mark as read" step.
Marking the item complete also clears it.

Each row also has a small ✉ icon — click it to email the owner
directly from the dashboard. A modal opens with the
recipient pre-filled (editable, but restricted to a known active user's
address), a subject automatically set from the record's type and number (e.g.
"Action Item #5: ..."), and a free-text note field. Sending
uses the same SMTP forwarder configured in Admin → Mail forwarder.

## Presentations

Use **Presentations** (`/presentations`) to track **Customer**, **Technical
Spotlight**, and **Event** presentations. Each record has a title, an existing
FOCUS user as owner, a selectable **Collaborate / Develop / Deliver** workflow
stage, an optional planned delivery date with a clickable calendar picker (or
manual YYYY-MM-DD entry), and a large editable notes section.
Filter the Presentations view by **Category** to see all presentations or just
Customer, Technical Spotlight, or Event records. Combine it with **Person** to
view a user's presentations within that category; **clear** resets both filters.
Stages can be changed in either direction; Deliver is a workflow stage, not
an automatic confirmation that delivery occurred.

Every signed-in user can view presentations. Members create presentations for
themselves and edit their own records. Managers and admins can edit any
presentation and assign or reassign its owner. **Create presentation / Save
changes** persists the record, including notes and delivery date; no separate
notes submission is needed.

Saved presentations also have **Related SharePoint documentation**: add multiple
named HTTPS links that appear as clickable pills and open in a new tab. The owner
and managers/admins can add or remove links; everyone can view them. Save any
presentation edits before adding a link, which is saved immediately. Removing a
link does not delete its SharePoint document or change document access permissions.
Links are stored in the same FOCUS database and included in backups.

Presentations use a new table in the **existing FOCUS SQLite database**, created
automatically on application startup without replacing tasks, action items,
users, or messages. Backups include presentation records; restoring an older
backup creates the missing table automatically. Metrics and the read-only
summary API report action items, without double-counting retained legacy TODO rows.

## Messages

Every user has their own **My Messages** queue at the top of the Work dashboard —
only messages addressed to them are shown. Each action item row has a
💬 icon (next to ✉) for sending a short, in-app ping (up to 250 characters)
to that record's owner/assignee — no email involved, and the recipient is
always locked to that record's owner/assignee (not user-selectable). Each
message shows the sender, timestamp, and a link back to the action item
it was about.

Each message has two actions: **↩ Reply** sends a new message straight back
to whoever sent the original (carrying the same action item context),
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

- Active/completed action item counts, plus blocked and overdue counts
- **Application usage by user** — a 3D-styled bar chart of audit-log activity
  (logins and action item changes) per person over a selectable window
  (7/30/90 days). Bar height and color intensity both scale with activity, so
  the most engaged user visually pops against everyone else — a quick read on
  who is (and isn't) actively using the system.
- Per-person open workload
- Stale items — open longer than `FOCUS_STALE_WEEKS` (default 2) without an
  update, flagged as likely obstacles
- Completion trend over the last 8 weeks
- The oldest active action items

## Roles & permissions

| Role      | Can do |
|-----------|--------|
| `member`  | Create action items for themselves or teammates without approval. Edit/reassign items they created or currently own. View team workloads and add notes. |
| `manager` | Everything a member can, plus edit or reassign **any** action item, bulk-transfer open work, and use the full admin console (users, invites, backups). |
| `admin`   | Same access as manager. Intended for whoever owns the deployment. |

## User management & invitations

The admin console (`/admin`, admin/manager only) works like HOLO:

- **Invite a user** — generates a single-use, expiring registration link.
  Copy/paste it or email it directly via the configured SMTP forwarder.
- **Users** — change role, reset password (temporary password, must change on
  next login), enable/disable, or delete (blocked while the user still owns
  action items, retained legacy work, presentations, notes, or messages. Disable departing users
  to preserve attribution and use Team View to transfer their open work).
- **System log** — every state-changing action (logins, action item/presentation
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
| `VISTA_BASE_URL` | `http://localhost:9098` | Browser-reachable VISTA-2 URL allowed as the return target after a HOLO identity hand-off. |
| `FOCUS_API_KEY` | *(empty — disabled)* | Enables the read-only `/api/v1/...` JSON API (see below). Callers send it in an `X-API-Key` header. |

## Read-only API for external integrations

`/api/v1/...` is a small, read-only JSON API for programmatic access — used by
**VISTA** to build its cross-application executive dashboard. It's guarded by a
static key (`FOCUS_API_KEY`) in an `X-API-Key` header, entirely separate from
the session-cookie auth used everywhere else. Leave `FOCUS_API_KEY` empty to
disable it (every route 404s).

| Route | Returns |
|---|---|
| `GET /api/v1/summary` | Active/completed action item counts, blocked/overdue and stale counts, per-person workload (including status and priority breakdowns), the 8-week completion trend, and oldest active items. Legacy task count fields remain present as zero for existing clients. |
| `GET /api/v1/users` | The user roster (id, email, role, active flag, forced-password-change flag) — never password hashes. |
| `GET /api/v1/activity?days=7\|30\|90` | Per-user audit-log activity count and most recent login over the window (the same data behind FOCUS's own usage chart). |

```bash
curl -H "X-API-Key: $FOCUS_API_KEY" http://localhost:9094/api/v1/summary
```

## Stack

FastAPI + Jinja2 + SQLAlchemy + SQLite. Passwords hashed with bcrypt; sessions
are signed cookies (Starlette `SessionMiddleware`). Single-container
deployment; no external services required (email is optional, via an
unauthenticated SMTP forwarder for invitations).
