# Shared UI Design Guide — opal, opal-mist, holo, focus, vista

Reference this file before making any visual/UI change in any of the five sibling
apps (`opal`, `opal-mist`, `holo`, `focus`, `vista`). Goal: converge on one
intentional look instead of five apps quietly drifting apart.

Methodology adapted from Anthropic's open-source `frontend-design` skill
(https://github.com/anthropics/skills/tree/main/skills/frontend-design,
Apache License 2.0) and grounded in this deployment's actual HPE dark theme.

## Current state: token drift (as of 2026-08-19)

`holo`, `focus`, and `vista` share one CSS variable system
(`app/static/style.css` in each). `opal` and `opal-mist` predate that
system and inline an older, different one per-template. They are **not**
the same today:

| Token | opal / opal-mist | holo / focus / vista |
|---|---|---|
| `--bg` | `#000000` | `#000000` |
| `--surface` (cards) | `#425563` | `#1a232b` |
| `--surface2` (raised/inputs) | `#80746e` | `#232f38` |
| border/line | `--border: rgba(198,201,202,0.25)` | `--line: rgba(198,201,202,0.18)` |
| primary text | `--text: #e1e1e1` | `--text: #e6e8ea` |
| secondary text | `--text2: #c6c9ca` | `--muted: #98a2ac` |
| brand green | `--happy: #01a982` | `--hpe-green: #01a982` |
| status colors | `--critical` / `--hot` / `--concerned` / `--stable` (churn-heat specific) | `--danger` / `--success-bg` (generic) |

Don't silently "fix" this by migrating one app's CSS to match another —
that's a visible, risky change across many templates and should be its own
deliberate task, not a side effect of an unrelated feature. Treat
**holo/focus/vista's system as the canonical target** (3 of 5 apps already
use it, and the naming is more semantic), and flag drift when you notice it,
but only migrate opal/opal-mist when asked to.

## Process for any new UI work

1. **Ground it.** Name the concrete page/component, its audience (exec
   glancing at a heat map vs. an admin filling a dense table), and its one
   job. Don't start from a blank template.
2. **Reuse tokens first.** Check the table above / the app's `style.css`
   (or inline `:root` block) before inventing a new color, radius, or
   spacing value. A new value needs a specific reason.
3. **Brainstorm before building**, in this order:
   - *Color* — which existing tokens, or (rarely) a justified new one.
   - *Type* — this deployment uses a plain system stack
     (`"Metric", -apple-system, ... sans-serif`); don't introduce a second
     display face without a reason.
   - *Layout* — a one-sentence description of the structure (e.g. "3-up
     stat cards, then a full-width trend chart, then a table").
   - *Signature* — is there one deliberate element that makes this view
     memorable/scannable, or is it just default cards-in-a-grid? Not every
     view needs one — dense admin tables don't — but dashboards do.
4. **Avoid AI-design defaults.** This deployment's near-black + single
   HPE-green-accent look is an intentional brand choice, not a generic
   default — keep it. But don't reach for other clichés inside it: numbered
   `01/02/03` markers where order isn't meaningful, gratuitous gradients,
   or animation added just to look "alive."
5. **Build, then look at it.** Use the browser tools (`screenshotPage` /
   `openBrowserPage` / snapshot) to actually view the rendered page —
   don't sign off from reading markup alone. Check text/muted contrast
   against both `--surface` and `--surface2`.
6. **Critique before calling it done.** Does it match the existing sibling
   apps' density and tone? Does it hold up at the viewport widths that
   matter for this app (these are desktop-oriented dashboards — say so if
   mobile doesn't matter for a given view)?

## When asking the AI assistant for UI changes

Vague requests ("make it nicer") force guessing. Specific, comparative
feedback converges faster:
- "Card padding feels cramped vs. the FOCUS dashboard cards."
- "`--muted` text fails contrast on `--surface2`."
- "Match the HOLO active-labs table style for this new table."

For any non-trivial visual change, ask for a screenshot before/after, and
consider asking for a second-pass critique (e.g. via a review agent) before
accepting it.
