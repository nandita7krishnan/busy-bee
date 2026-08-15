# busy-bee

A macOS menu bar app that gives a single glanceable view across all
active Claude Code side projects: what got done recently, what's
next, what's blocked, and what the agent is waiting on you to answer.
Clicking a project opens a terminal and resumes that project's Claude
Code session directly.

See [`docs/prd.md`](./docs/prd.md) for the full spec this was built from.

## Architecture

```
Claude Code session (per project, in terminal)
        |
        v
Status update (dashctl CLI, reinforced by a Stop hook)
        |
        v
Per-project status file (.claude-dashboard/status.json)
        |
        v
Aggregator (watches all known project paths)
        |
        v
Central store (SQLite, ~/.claude-dashboard/db.sqlite)
        |
        v
Menu bar widget (rumps + pywebview popover)
        |
        +--> Click project name -> opens Terminal, cd + claude --continue
        +--> Manual edits (resolve) -> written back into the central store directly
```

## Install

```
./scripts/install.sh
```

This creates a `.venv`, installs the package + `rumps`/`pywebview`, and
symlinks `dashctl` and `busy-bee` into `~/.local/bin`. Make sure that's
on your `PATH`.

It also runs `dashctl setup-global` for you (see below) -- one-time,
machine-wide setup, so no individual project needs any manual wiring.

## Usage

**Tracking projects is automatic.** `dashctl setup-global` (run once by
the installer, or re-run any time with `dashctl setup-global`) installs
[`claude_md_snippet.md`](./claude_md_snippet.md) into
`~/.claude/CLAUDE.md` and the [`Stop` hook](./hooks/stop_hook.py) into
`~/.claude/settings.json` at the Claude Code *user* level, so it
applies to every project, not just ones you remember to configure.
From there, any project auto-registers itself the first time an agent
in it calls `dashctl` -- no `dashctl init`, no per-project CLAUDE.md
edits, no per-project hook config.

(`dashctl init [--name NAME]` still exists if you want to register a
project under a name other than its directory's basename, or register
it before the agent logs anything.)

**Log status** (this is what the agent calls mid-session, and what the
`Stop` hook nudges it to do if it forgets):

```
dashctl done "<what got finished>"
dashctl todo "<what's next>"
dashctl blocker "<what's blocking progress>"
dashctl question "<what needs a decision from you>"
dashctl resolve blocker|question <id>
```

**Run the dashboard:**

```
busy-bee
```

Starts the tray icon (🐝), the aggregator (polls every 5s by default,
configurable in `~/.claude-dashboard/config.json`), and the popover UI.
Click the tray icon's "Show Dashboard" item to open it. Click a
project name inside a card to open a terminal and resume that
project's Claude Code session.

## Repo layout

```
busy_bee/
  cli.py              dashctl entrypoint
  project_store.py    per-project status.json read/write
  config.py           ~/.claude-dashboard/config.json handling
  db.py                central SQLite schema + queries
  aggregator.py         polls project paths, merges into the central store
  terminal_launcher.py  osascript-driven click-to-resume
  app.py                 rumps tray app + pywebview popover wiring
  ui/                     popover.html/css/js
hooks/stop_hook.py     Claude Code Stop hook (the safety net)
claude_md_snippet.md   paste into each tracked project's CLAUDE.md
scripts/install.sh
tests/
```

## Known v1 limitations

- Clicking the tray icon shows a one-item menu ("Show Dashboard")
  rather than opening the popover directly on click -- `rumps` doesn't
  expose binding an arbitrary handler straight to the status item
  without going through its menu. One extra click.
- The popover doesn't auto-dismiss on click-outside yet; toggle it via
  the tray menu.
- No fade/drop-off behavior yet for projects idle for N+ days (open
  question in the PRD).
- Terminal.app is the default launch target; iTerm is supported by
  setting `"terminal_app": "iTerm"` in the config, but isn't
  auto-detected.

## Tests

```
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```
