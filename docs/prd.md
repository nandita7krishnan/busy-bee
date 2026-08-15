# PRD: side project dashboard

## Overview
A macOS menu bar app that gives a single glanceable view across all active Claude Code side projects: what got done recently, what's next, what's blocked, and what the agent is waiting on you to answer. Clicking a project opens a terminal and resumes that project's Claude Code session directly.

## Problem statement
Side projects run as separate Claude Code sessions in separate terminal tabs. Context switching between them means either keeping a pile of terminal windows open, or losing track of what state each project is in. There's no single place to see "what did I finish, what's next, what's stuck" across everything at once, and re-entering a project requires remembering which folder and which conversation to resume.

## Goals
- One glance tells you the state of every project: active, idle, or blocked.
- Full history of done/todo/blockers/questions is preserved per project, but the UI only ever surfaces the last 3 done and next 3 todo items.
- Blockers and agent questions are impossible to miss, they're visually distinct and badge the tray icon.
- One click drops you back into the actual terminal conversation for that project, no manual `cd` or session hunting.
- Always visible, always current, low friction to check and low friction to ignore.

## Non-goals (v1)
- No mobile or web version, macOS menu bar only.
- No editing of the underlying Claude Code conversation from the dashboard itself.
- No cross-machine sync, local SQLite only.
- No support for non-Claude-Code agents in v1 (Cursor, Aider, etc).

## User
A single user (you), running roughly 5-10 side projects at varying levels of activity, using Claude Code in Terminal per project.

## System architecture

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
        +--> Manual edits -> written back into the central store directly
```

### Components

**dashctl (CLI)**
A small command the agent calls directly, so status capture doesn't depend on parsing free-text logs.
- `dashctl done "<text>"`
- `dashctl todo "<text>"`
- `dashctl blocker "<text>"`
- `dashctl question "<text>"`
- `dashctl resolve blocker|question <id>`

Each command appends a timestamped row to that project's local status store and is instant, non-interactive, safe for the agent to call mid-session.

**CLAUDE.md convention**
Every tracked project gets a standard snippet instructing the agent: log a `done` item whenever a task completes, log a `blocker` when it can't proceed without you, log a `question` when it needs a decision from you, and check `dashctl` is available before logging.

**Stop hook (safety net)**
Fires at the end of a Claude Code turn. If nothing was logged that turn, it prompts the agent to log a one-line status before finishing, so tracking doesn't depend on the agent remembering unprompted.

**Aggregator**
A lightweight watcher that scans a configured list of project paths, reads each project's local status data, and merges it into the central SQLite store. Runs on an interval or on file change, whichever is simpler to build reliably.

**Central store (SQLite)**
Single source of truth for the dashboard UI. Schema (see below). Full history retained forever, nothing deleted.

**Menu bar widget**
`rumps` for the tray icon and app lifecycle, `pywebview` for the popover UI (HTML/CSS, matches the mockups already agreed on). Reads from the central store, never writes to project files directly except when you manually add/edit an item.

**Terminal launcher**
`osascript` driven: opens Terminal (or iTerm if that's the default), `cd`s to the project path, runs `claude --continue`.

## Data model

```sql
CREATE TABLE items (
  id INTEGER PRIMARY KEY,
  project TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('done','todo','blocker','question')),
  text TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  resolved_at TIMESTAMP,        -- null until a blocker/question is resolved
  source TEXT NOT NULL DEFAULT 'agent'  -- 'agent' or 'manual'
);

CREATE TABLE projects (
  name TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'idle'  -- 'active','idle','blocked'
);
```

Display logic: `done` shows the 3 most recent by `created_at`, `todo` shows the next 3 unresolved, `blocker`/`question` show all unresolved (both counted for badges).

## UI/UX spec

Chosen direction: colored, collapsible card stack (Option B, agreed in brainstorming).

- One card per project, stacked vertically in the popover.
- Left border color signals state at a glance: coral for an open blocker, amber for an open question, teal for active with nothing pending, gray for idle.
- Header row: project name (click to open terminal), badge(s) for blocker/question counts if any, chevron to collapse/expand.
- Expanded body: two columns, "Done" (last 3, muted strikethrough) and "Next" (next 3, plain text), plus a plain-language line at the bottom for any open blocker or question.
- Default expand state on open: any card with an open blocker or question starts expanded, everything else starts collapsed. This resets every time the popover opens rather than persisting prior manual collapse/expand choices, so nothing new gets missed.
- Tray icon itself carries a small red badge with a count whenever any project has an unresolved blocker or question, so you know to check without opening the popover.

## Key workflows

**Agent completes a task**
Agent calls `dashctl done "..."` mid-session. Aggregator picks it up. Dashboard's "done" list for that project updates within one polling interval.

**Agent gets blocked**
Agent calls `dashctl blocker "..."`. Card border turns coral, badge appears, tray icon badges. You see it without hunting through terminal scrollback.

**You resume a project**
Click the project name in its card. Terminal opens, cds into the project, resumes the Claude Code session with `claude --continue`. You're back in context immediately.

**You resolve a blocker manually**
From the dashboard (or by telling the agent directly, which then calls `dashctl resolve`), the blocker clears and the card border returns to its normal state.

## Tech stack
- Python, `rumps` for the menu bar app shell
- `pywebview` for the popover UI (HTML/CSS matching the agreed mockup)
- SQLite for the central store
- Claude Code `Stop` hook + `CLAUDE.md` snippet for status capture reinforcement
- `dashctl`, a small Python CLI, installed once and referenced from each project's `CLAUDE.md`
- `osascript` for terminal launch/resume

## Open questions
- Should collapse state persist across popover opens for non-flagged projects, or always reset per the current plan? (Current answer: always reset.)
- iTerm vs Terminal.app as the launch target, or make it configurable.
- Polling interval for the aggregator vs a file-watcher approach (fswatch/watchdog).
- What happens to a project that hasn't logged anything in N days, does it visually fade or drop off the active list?

## Build phases
1. `dashctl` CLI + SQLite schema (foundation, testable standalone)
2. `CLAUDE.md` snippet + `Stop` hook wiring on one real project
3. Aggregator + central store population from multiple projects
4. Menu bar widget UI (static, reading from store)
5. Click-to-resume terminal launch
6. Manual edit support from the widget
7. Tray icon badge for outstanding blockers/questions

## Success metrics
- You can tell the state of every project within 2 seconds of opening the popover.
- Zero missed blockers or questions, badge visibility is the test.
- Resuming any project takes one click, no manual terminal setup.
