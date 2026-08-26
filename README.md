# busy-bee

A macOS menu bar app that gives a single glanceable view across all
active Claude Code side projects: what got done recently, what's
next, what's blocked, and what the agent is waiting on you to answer.
Clicking a project opens a terminal and resumes that project's Claude
Code session directly. You can also jot down a project that doesn't
exist yet, queue tasks against it, and hand those tasks to Claude the
moment you create its folder.

See [`docs/prd.md`](./docs/prd.md) for the full spec this was built from.

## Requirements

- **macOS.** Non-negotiable: menu bar status item, AppKit dialogs, and
  `osascript`-driven Terminal control. The installer refuses to run
  anywhere else.
- **Python 3.10+**, and it must be the `python3` the installer finds
  first. Machines with Anaconda or Xcode's python3 ahead on `PATH`
  often have 3.8/3.9 there -- check with `python3 --version` and pass
  `PYTHON=` if it's too old (see step 1).
- **[Claude Code](https://claude.com/claude-code)**, since everything
  on the dashboard is logged by agents running in it.
- **Terminal.app** (default) or **iTerm** for click-to-resume.

No Homebrew packages, no Xcode, no code signing -- `pip` pulls
`rumps` and `pywebview` (and PyObjC underneath) into a local venv.

## Quick start

Fine to run start-to-finish by an agent; every step is
non-interactive and idempotent.

```bash
git clone https://github.com/nandita7krishnan/busy-bee.git ~/busy-bee   # keep the clone somewhere permanent
cd ~/busy-bee
./scripts/install.sh                 # venv, PATH symlinks, Claude Code hooks, LaunchAgent
```

Then verify:

```bash
dashctl --help                       # prints usage -> dashctl is on PATH
pgrep -f 'busy-bee' >/dev/null && echo running   # the menu bar app is up
```

You should see a 🐝 in the menu bar within a few seconds. From then
on, every Claude Code session on the machine logs to it automatically
-- no per-project setup.

## Installation, step by step

The same install as above, one step at a time, with what to expect and
what to do when it doesn't match. Several of these caveats were
debugged live; they're real, not hypothetical.

### 1. Clone and run the installer

```bash
git clone https://github.com/nandita7krishnan/busy-bee.git
cd busy-bee
./scripts/install.sh
```

This single command creates a `.venv`, installs the package plus
`rumps`/`pywebview`, symlinks `dashctl` and `busy-bee` onto `PATH`,
wires Claude Code up globally (step 3), and installs + starts a
`launchd` agent that runs the app (step 4).

**Leave the clone where you put it.** The Claude Code hooks and the
LaunchAgent both reference absolute paths into this directory
(`~/.claude/settings.json` points at `hooks/*.py`; the plist points at
`.venv/bin/busy-bee`). Moving or renaming the folder later breaks both
until you re-run `./scripts/install.sh` from the new location.

If `python3` is older than 3.10, the installer stops before doing
anything and tells you so. Point it at a newer interpreter:

```bash
PYTHON=/opt/homebrew/bin/python3.12 ./scripts/install.sh
```

### 2. Confirm `dashctl` is actually on PATH

```bash
dashctl --help
```

`install.sh` picks a symlink directory automatically -- it prefers
wherever `claude` itself lives (e.g. `/opt/homebrew/bin`), since
that's guaranteed to already be on `PATH` on a machine running Claude
Code. If it had to fall back to `~/.local/bin`, it prints an explicit
`WARNING` and you'll need to add that to your shell's `PATH` yourself
(e.g. `export PATH="$HOME/.local/bin:$PATH"` in `~/.zshrc`), or
`dashctl` will silently fail to be found from new terminals. You can
also choose the directory up front with `BIN_DIR=... ./scripts/install.sh`.

### 3. Verify the global Claude Code wiring

`install.sh` runs `dashctl setup-global`, which installs
[`claude_md_snippet.md`](./claude_md_snippet.md) into
`~/.claude/CLAUDE.md` (between `<!-- busy-bee:start -->` /
`<!-- busy-bee:end -->` markers) and the [`Stop`](./hooks/stop_hook.py),
[`SessionStart`](./hooks/session_start_hook.py), and
`PostToolUse`/`TodoWrite` (`hooks/todo_sync_hook.py`) hooks into
`~/.claude/settings.json`, all at the Claude Code *user* level. This
is what makes tracking automatic: every Claude Code session on the
machine picks up the instructions, and any project auto-registers
itself the moment a session opens in it (the `SessionStart` hook), or
at the latest the first time an agent in it calls `dashctl` -- no
`dashctl init`, no per-project CLAUDE.md edits, no per-project hook
config needed.

Check it landed:

```bash
grep -c busy-bee ~/.claude/CLAUDE.md          # >= 1
grep -c busy-bee/hooks ~/.claude/settings.json # 3 (Stop, SessionStart, TodoWrite)
```

The hooks are registered to run under plain `python3`, not the venv's
-- they only import this repo's stdlib-only modules, so they keep
working even if the venv is rebuilt, but a `python3` does have to
exist on `PATH` in whatever environment Claude Code runs hooks from.

**Note:** this only affects sessions that read `~/.claude/CLAUDE.md`
*after* `setup-global` ran. A Claude Code session already running when
you install this won't retroactively know about it -- either tell it
directly to run `dashctl`, or start a fresh session in that project.

(`dashctl init [--name NAME]` still exists if you want to register a
project under a name other than its directory's basename, or register
it before an agent has logged anything there. `dashctl untrack NAME`
does the reverse -- stops tracking a project and deletes its logged
items from the central store, e.g. to clean up a stray registration.)

**Note:** `$HOME` itself is never auto-registered, even if a Claude
Code session runs directly in it (not inside an actual project) --
this happened live during testing and silently created a
"yourusername" card. `dashctl init` still allows it explicitly, if
that's really wanted.

### 4. It's already running; here's how to reopen or quit it

`install.sh` installs and starts a `launchd` agent
(`~/Library/LaunchAgents/dev.busybee.app.plist`) that runs `busy-bee`
once automatically: now, and again every time you log in. It does
*not* restart itself if you quit it -- quitting from the tray menu
("Quit" -- rumps adds this automatically) actually quits, and it stays
quit until you bring it back.

Look for the small 🐝 icon in your menu bar (top-right strip) --
easy to miss among other menu bar icons, but it should be there within
a few seconds of running the installer. It also shows up in the
Dock with the same bee icon (busy_bee/icon.py renders it), and either
one badges with a red circle + number whenever there's an unresolved
blocker/question anywhere -- the Dock badge is macOS's native
`NSDockTile.badgeLabel`; the menu bar one is hand-composited to match,
since status items don't have an equivalent native badge API. There's
also a small floating widget -- same bee icon, always on top of other
windows, draggable anywhere on screen (click-and-drag moves it, a
plain click opens the dashboard, same as the tray menu). Only the bee
itself and its badge catch clicks; the transparent space around them
passes clicks through to whatever window is behind, so parking the
widget over something you still need to use is fine. Click either
the tray icon → "Show Dashboard", or the widget directly, to open the
popover. Clicking the popover window's red close button hides it
rather than actually closing/destroying it, so "Show Dashboard" keeps
working afterward -- consistent with the rest of the app staying alive
in the background.

**If you quit it and want it back, launch "Open Busy Bee" from
Spotlight, Launchpad, or Finder (`/Applications`)** -- `install.sh`
also builds this as a separate tiny app
(`scripts/build_reopener_app.sh`). It's not the same app as busy-bee
itself: it doesn't touch the menu bar or create any UI at all, it just
tells `launchd` to restart the real busy-bee LaunchAgent and
immediately exits. This split exists because launching *busy-bee
itself* as a normal macOS app (Spotlight, Launchpad, double-click) is
verified broken (see Known limitations) -- but a launcher that does
nothing but run a `launchctl` command and quit never hits that
problem, since it's the *target* process creating a status item that
fails under Launch Services, not the launching one.

**Don't pin "Open Busy Bee" to the Dock** -- busy-bee itself already
has a Dock icon (with the same bee art and badge) whenever it's
running, so pinning the reopener too just shows two icons for the same
thing. If you already dragged it there, drag it back off, or right-
click → Options → Remove from Dock.

`bash scripts/install_launch_agent.sh` reinstalls and restarts the
agent directly (equivalent to what "Open Busy Bee" does, but from a
terminal). See [Troubleshooting](#troubleshooting) if the icon never
shows up.

### 5. Log some status and watch it show up

From inside any project directory:

```bash
dashctl done "<what got finished>"
dashctl todo "<what's next>"
dashctl blocker "<what's blocking progress>"
dashctl question "<what needs a decision from you>"
dashctl summary "<one sentence on where things stand>"
dashctl resolve blocker|question|todo <id>
```

A manually-logged `todo` (as opposed to one synced from `TodoWrite`,
which clears itself automatically) has no way to disappear from "Next"
except `resolve` or getting pushed out by 3 newer todos -- forgetting
this was a real bug hit live (a card's "Next" column showed hours-old
stale items because nothing had ever resolved or superseded them).

`summary` is different from the rest: it's a single line shown next to
the project name in its card, not a growing list -- each new one
overwrites the last. `todo` items also get populated automatically if
the agent uses Claude Code's own `TodoWrite` tool, via a
`PostToolUse`/`TodoWrite` hook (`hooks/todo_sync_hook.py`,
`busy_bee/todo_sync.py`) installed by the same `dashctl setup-global`
-- no separate `dashctl todo` call needed for items already tracked
there; completed ones become `done`s automatically too.

The aggregator polls every 5s by default (configurable in
`~/.claude-dashboard/config.json`), so give it a few seconds, then
reopen the popover -- that project's card should now be there.

## Using the dashboard

### Cards for real projects

Every card is scoped to sessions with a currently-live `claude`
process, keyed by terminal tty + Claude Code's own per-invocation
session id (a tty gets reused across unrelated sessions in the same
terminal window, which the session id disambiguates). Once a
session's terminal closes, its whole card disappears -- its done/todo
history isn't lost (still in `status.json`/the central db, and comes
back if that session ever logs again), it just stops rendering. Any
blocker/question it left unresolved is auto-resolved at that point
too, rather than lingering on the project's badge forever.

Click a project name to open a terminal and resume that project's
Claude Code session (or focus the existing one, if it's already open
-- see Architecture). With several live sessions, each session block
has its own clickable header instead. Blocker and question lines are
clickable too, and take you to the session that raised them.

These cards are a read-only mirror of what agents actually logged:
nothing on them can be edited or ticked off by hand, because doing so
would let the dashboard drift from the terminal it's reflecting.
Resolution happens in the session, via `dashctl resolve`.

### Cards for projects that don't exist yet

The box at the top of the popover ("what else is cooking?") adds a
**placeholder card** -- a project you've thought of but haven't
created a folder for. These are the one editable thing on the
dashboard, since you typed them rather than an agent logging them:

- **`+ Task`** in the card header expands it and drops the cursor in
  the "Add a task" box. Placeholder cards render collapsed by default.
- **The checkbox** on any task toggles it between Next and Done, both
  directions.
- **`×` on a task row** (appears on hover) deletes it.
- **`×` in the card header** (appears when you hover the card) deletes
  the whole card. If it still holds tasks, it asks first -- those
  tasks live nowhere else.
- **`Create folder…`** turns it into a real project: pick a parent
  directory, and it creates `<parent>/<name>`, registers it, and
  starts tracking it. If the card has unresolved tasks, it then asks
  whether to **hand them off to Claude** (writes them into the new
  project's `status.json` *and* opens a session there prompted with
  the list) or **keep them in the dashboard** (they stay manual, and
  keep showing on the now-real project's card).

Placeholder cards live in `~/.claude-dashboard/placeholders.json`,
deliberately outside both `config.json` and the SQLite store -- see
the module docstring in `busy_bee/placeholder_store.py` for why.

### Where state lives

```
~/.claude-dashboard/config.json        tracked projects, poll interval, terminal app
~/.claude-dashboard/db.sqlite          central store the popover reads
~/.claude-dashboard/placeholders.json  manual cards + their tasks
<project>/.claude-dashboard/status.json  per-project log the aggregator polls
/tmp/busybee-agent.log                 the app's stdout/stderr
```

`config.json` is also where you switch terminals
(`"terminal_app": "iTerm"`) or change `poll_interval_seconds`.

## Updating after pulling new code

The LaunchAgent runs `.venv/bin/busy-bee` directly, not a frozen
build, so restarting the agent is enough to pick up code changes:

```bash
git pull
./scripts/install.sh    # re-runs pip install -e, re-wires hooks, restarts the agent
```

Re-running the full installer is the safe default -- it's idempotent,
and it also re-points the hooks if the repo moved or a Claude Code
update reset `~/.claude/settings.json`. If you only changed Python/UI
code and nothing else, `bash scripts/install_launch_agent.sh` alone
restarts the app.

Changes to [`claude_md_snippet.md`](./claude_md_snippet.md) need
`dashctl setup-global` specifically -- the copy that agents actually
read lives between the markers in `~/.claude/CLAUDE.md`, and only that
command rewrites it. Sessions already running keep the old copy until
they restart.

## Uninstalling

```bash
# 1. stop the app and remove the LaunchAgent
launchctl unload ~/Library/LaunchAgents/dev.busybee.app.plist
rm ~/Library/LaunchAgents/dev.busybee.app.plist
rm -rf "/Applications/Open Busy Bee.app"

# 2. drop the CLI symlinks (wherever install.sh put them)
rm -f "$(dirname "$(command -v dashctl)")"/{dashctl,busy-bee}

# 3. remove the Claude Code wiring by hand:
#    - delete the <!-- busy-bee:start -->...<!-- busy-bee:end --> block
#      from ~/.claude/CLAUDE.md
#    - delete the three entries mentioning busy-bee/hooks from
#      ~/.claude/settings.json (Stop, SessionStart, PostToolUse)

# 4. optional: forget every logged item and manual card
rm -rf ~/.claude-dashboard
```

Per-project `.claude-dashboard/status.json` files stay behind in each
tracked project; delete them if you want the projects fully clean.

## Troubleshooting

**No 🐝 in the menu bar.** Check what's running and what it said:

```bash
pgrep -fl busy-bee
tail -20 /tmp/busybee-agent.log
bash scripts/install_launch_agent.sh   # reinstall + restart the agent
```

**`dashctl: command not found`** in a new terminal -- the symlink dir
isn't on `PATH` (see step 2). Add it to `~/.zshrc` and open a new
terminal, or re-run the installer with `BIN_DIR=` set to a directory
that is.

**A project never appears on the dashboard.** Cards only render for
sessions with a live `claude` process, so first make sure one is
actually running in that directory. Then check the wiring reached it:
`grep busy-bee ~/.claude/CLAUDE.md` and confirm the session started
*after* `setup-global` ran (step 3) -- an older session won't have
read the instructions. Logging one item by hand (`dashctl done "test"`)
from inside the project is the fastest way to tell whether the CLI
side works.

**An app icon looks wrong/generic/muted right after (re)building it**
-- that's very likely a stale icon cache, not a bad icon file.
Confirmed live: `iconutil -c iconset` on the actual built `.icns`
showed the correct art even when the Dock was rendering something
washed-out. `killall Dock` (safe, it relaunches instantly, no data
loss) forces a re-render and usually fixes it immediately.

**The installer stops on the Python version.** `python3` is older than
3.10; re-run as `PYTHON=/path/to/python3.12 ./scripts/install.sh`.

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
        +--> Click project name -> focuses that project's existing
        |    Terminal tab if one's already running claude, else opens
        |    a new one with cd + claude --continue
        +--> Placeholder cards (add/edit/delete tasks, delete card)
             -> ~/.claude-dashboard/placeholders.json, the only state
                the UI writes; agent-logged items stay read-only here
```

Terminal reuse works by tagging every `dashctl` log with the tty of
its owning `claude` process (found by walking up the process tree,
`process_utils.find_claude_ancestor_tty()`) -- matching by the
`claude` process's own reported cwd doesn't work, since Claude Code's
Bash tool runs each command as a detached subprocess and tracks `cd`
internally rather than by moving the parent process's actual OS
working directory.

## Repo layout

```
busy_bee/
  cli.py                dashctl entrypoint
  project_store.py      per-project status.json read/write
  placeholder_store.py  manual cards + their tasks (placeholders.json)
  config.py             ~/.claude-dashboard/config.json handling
  colors.py             per-project palette slots (shared with Terminal tab tints)
  process_utils.py      finds which terminal tty a dashctl call came from
  db.py                 central SQLite schema + queries
  aggregator.py         polls project paths, merges into the central store
  terminal_launcher.py  osascript-driven click-to-resume / terminal reuse
  dialogs.py            native folder picker + confirm alerts
  app.py                rumps tray app + pywebview popover wiring + the JS-facing Api
  icon.py               renders the bee icon (menu bar + Dock, badge composited in)
  click_through.py      makes the floating widget click-through except over the bee's silhouette
  todo_sync.py          syncs Claude Code's TodoWrite list into dashctl
  global_setup.py       installs the CLAUDE.md snippet + Stop/SessionStart/PostToolUse hooks globally
  ui/                   popover.html/css/js, widget.html/js (floating icon)
hooks/
  stop_hook.py           Claude Code Stop hook (the safety net, also nudges periodic summaries)
  session_start_hook.py  Claude Code SessionStart hook -- registers the directory and marks the new session before it logs anything
  todo_sync_hook.py      PostToolUse/TodoWrite hook -- calls busy_bee/todo_sync.py
claude_md_snippet.md   installed into ~/.claude/CLAUDE.md by setup-global
scripts/
  install.sh                full install
  install_launch_agent.sh   installs/starts the launchd agent that runs the app
  build_reopener_app.sh     builds "Open Busy Bee.app" -- restarts the agent via GUI
tests/
```

## Known limitations

- **Launching as a normal macOS app (Spotlight/Launchpad/double-click)
  is fundamentally broken -- use the LaunchAgent instead (see step 4
  above).** This was tried first and seemed to work at a process
  level (`ps` showed it running, no crash), but the tray icon never
  actually appeared. Root-caused live via Console (`log show`): macOS's
  Launch Services registers a GUI-launched process (`open -a`,
  double-click, Spotlight, Launchpad -- all go through the same
  `LSOpenApplication`-style path) differently from a plain subprocess
  launch, and Control Center's status-item XPC service
  (`com.apple.controlcenter.statusitems`) refuses the connection every
  single time for a Launch-Services-launched instance of this app --
  `scene activation failed: ... BSServiceConnectionErrorDomain ...
  "XPC error received on message reply handler"`, retried
  continuously, never succeeding. A plain subprocess launch (Terminal,
  or a `launchd` agent -- neither goes through `LSOpenApplication`)
  works every time, immediately, no errors. Compounding this: the
  `.app` bundle also had the wrong bundle identity for unrelated
  reasons (`Contents/MacOS/BusyBee` `exec`s the venv's `busy-bee`,
  whose shebang resolves through Homebrew's Python framework, which
  re-execs into *its own* `Python.app` -- Launch Services then
  registers the process as `org.python.python`, not `dev.busybee.app`,
  confirmed via `lsappinfo list`). Fixing *that* alone
  (`__CFBundleIdentifier` in the launcher script) did not fix the
  status-item failure, since that env var only changes what
  `NSBundle.mainBundle()` reports from inside the process, not how
  Launch Services classified the launch. Given neither issue is fixable
  from a shell-script wrapper, the `.app` bundle approach was dropped
  entirely in favor of the `launchd` agent, which sidesteps both
  problems by not being a Launch-Services "app" launch at all. A
  proper `py2app` build (private embedded Python framework, no foreign
  bundle to get misattributed to) might make a real double-clickable
  `.app` viable again, but hasn't been tried. Workaround in place:
  "Open Busy Bee.app" (`scripts/build_reopener_app.sh`) is a separate,
  GUI-launchable app that never creates a status item itself -- it
  only runs `launchctl kickstart` on the real LaunchAgent and exits --
  so its own Launch-Services launch never hits this bug.
- Clicking the tray icon shows a one-item menu ("Show Dashboard")
  rather than opening the popover directly on click -- `rumps` doesn't
  expose binding an arbitrary handler straight to the status item
  without going through its menu. One extra click.
- The popover doesn't auto-dismiss on click-outside yet; toggle it via
  the tray menu.
- No fade/drop-off behavior yet for projects idle for N+ days (open
  question in the PRD).
- Terminal.app is the default launch target and the only one with
  reuse detection; iTerm is supported for opening new windows (set
  `"terminal_app": "iTerm"` in the config) but always opens a new
  window rather than reusing an existing session.

## For contributors: things that look like bugs but aren't (and vice versa)

- **rumps and pywebview both want to own the main thread's Cocoa event
  loop; only one can.** `pywebview.start()` requires the main thread
  and refuses otherwise, so it wins; rumps' `App.run()` is invoked
  with its final blocking call (`AppHelper.runEventLoop`) neutered so
  it just does its setup (status item, menu, timers) and returns,
  scheduled onto the main thread via `AppHelper.callAfter` once
  pywebview's loop is live. See the `busy_bee/app.py` module docstring
  before touching this -- it was built by hitting the crash first, not
  designed abstractly.
- **Never call `window.evaluate_js()` from the main thread.** It
  schedules JS execution back onto the main thread via
  `AppHelper.callAfter` and then blocks synchronously waiting for the
  result. Called from a `rumps.clicked` callback (which already runs
  on the main thread), that's the thread waiting on itself -- a
  permanent deadlock (cursor spins, nothing happens), not just
  slowness. Always dispatch it from a throwaway background thread
  (see `show_dashboard`/`_refresh_popover` in `app.py`).
- **Don't drive periodic UI refresh from a JS `setInterval` in the
  popover.** One was tried for polling `get_projects()`; confirmed
  live that it silently stopped refreshing (or never reliably started)
  while a separate Python-side `rumps.Timer` on the exact same 5s
  cadence, driving the tray badge, kept working the whole time. The
  popover's periodic refresh is now driven from that same Python timer
  (`start_badge_timer`'s tick also spawns `_refresh_popover` on a
  background thread) instead of trusting a JS timer with no visibility
  into whether it's actually still running.
- **Don't point an `<img src="file://...">` at a local file from
  `popover.html`/`widget.html`.** Any bare filesystem path passed as a
  window's `url` (not prefixed `file://`) is served over
  `http://127.0.0.1` by pywebview's own local server, not loaded
  directly -- so the *page* itself is `http://`, and WKWebView silently
  blocks an `http://` page from loading `file://` resources. Confirmed
  live: the widget's icon `<img>` had `naturalWidth`/`naturalHeight`
  stuck at `0x0` despite the file genuinely existing at that path, no
  console error. Use a `data:` URI instead (see
  `Api.get_widget_icon_data_uri`) -- not subject to that restriction.
- **The popover rebuilds `#cards` wholesale every 5s.** Anything
  stateful in there (a half-typed task, focus) would be destroyed by
  the refresh, so `render()` defers while an input inside `#cards` has
  focus and replays on `focusout`. The "add project" box deliberately
  lives *outside* `#cards` for the same reason.

## Tests

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```
