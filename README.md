# busy-bee

A macOS menu bar app that gives a single glanceable view across all
active Claude Code side projects: what got done recently, what's
next, what's blocked, and what the agent is waiting on you to answer.
Clicking a project opens a terminal and resumes that project's Claude
Code session directly.

See [`docs/prd.md`](./docs/prd.md) for the full spec this was built from.

## Installation

Follow these steps in order. Each one says what to expect and what to
do if it doesn't match -- several of these were debugged live, so the
caveats are real, not hypothetical.

### 1. Clone and run the installer

```
git clone <this repo>
cd busy-bee
./scripts/install.sh
```

This single command creates a `.venv`, installs the package plus
`rumps`/`pywebview`, symlinks `dashctl` and `busy-bee` onto `PATH`,
wires Claude Code up globally (step 3), and installs + starts a
`launchd` agent that runs the app (step 4).

### 2. Confirm `dashctl` is actually on PATH

```
dashctl --help
```

`install.sh` picks a symlink directory automatically -- it prefers
wherever `claude` itself lives (e.g. `/opt/homebrew/bin`), since
that's guaranteed to already be on `PATH` on a machine running Claude
Code. If it had to fall back to `~/.local/bin`, it prints an explicit
`WARNING` and you'll need to add that to your shell's `PATH` yourself
(e.g. `export PATH="$HOME/.local/bin:$PATH"` in `~/.zshrc`), or
`dashctl` will silently fail to be found from new terminals.

### 3. Verify the global Claude Code wiring

`install.sh` runs `dashctl setup-global`, which installs
[`claude_md_snippet.md`](./claude_md_snippet.md) into
`~/.claude/CLAUDE.md` and the [`Stop` hook](./hooks/stop_hook.py) into
`~/.claude/settings.json`, both at the Claude Code *user* level. This
is what makes tracking automatic: every Claude Code session on the
machine picks up the instructions, and any project auto-registers
itself the first time an agent in it calls `dashctl` -- no
`dashctl init`, no per-project CLAUDE.md edits, no per-project hook
config needed.

**Note:** this only affects sessions that read `~/.claude/CLAUDE.md`
*after* `setup-global` ran. A Claude Code session already running when
you install this won't retroactively know about it -- either tell it
directly to run `dashctl`, or start a fresh session in that project.

(`dashctl init [--name NAME]` still exists if you want to register a
project under a name other than its directory's basename, or register
it before an agent has logged anything there.)

### 4. It's already running; here's how to reopen or quit it

`install.sh` installs and starts a `launchd` agent
(`~/Library/LaunchAgents/dev.busybee.app.plist`) that runs `busy-bee`
once automatically: now, and again every time you log in. It does
*not* restart itself if you quit it -- quitting from the tray menu
("Quit" -- rumps adds this automatically) actually quits, and it stays
quit until you bring it back.

Look for the small 🐝 icon in your menu bar (top-right strip) --
easy to miss among other menu bar icons, but it should be there within
a few seconds of running the installer. Click it → "Show Dashboard" to
open the popover. Click a project name inside a card to open a
terminal and resume that project's Claude Code session (or focus the
existing one, if it's already open -- see Architecture). Clicking the
popover window's red close button hides it rather than actually
closing/destroying it, so "Show Dashboard" keeps working afterward --
consistent with the rest of the app staying alive in the background.

**If you quit it and want it back, launch "Open Busy Bee" from
Spotlight, Launchpad, or the Dock** -- `install.sh` also builds this
as a separate tiny app (`scripts/build_reopener_app.sh`). It's not the
same app as busy-bee itself: it doesn't touch the menu bar or create
any UI at all, it just tells `launchd` to restart the real busy-bee
LaunchAgent and immediately exits. This split exists because launching
*busy-bee itself* as a normal macOS app (Spotlight, Launchpad,
double-click) is verified broken (see Known limitations) -- but a
launcher that does nothing but run a `launchctl` command and quit
never hits that problem, since it's the *target* process creating a
status item that fails under Launch Services, not the launching one.

If the icon doesn't appear after either path, check what's actually
running:

```
ps aux | grep busy-bee
tail -20 /tmp/busybee-agent.log
```

`bash scripts/install_launch_agent.sh` reinstalls and restarts the
agent directly (equivalent to what "Open Busy Bee" does, but from a
terminal).

### 5. Log some status and watch it show up

From inside any project directory:

```
dashctl done "<what got finished>"
dashctl todo "<what's next>"
dashctl blocker "<what's blocking progress>"
dashctl question "<what needs a decision from you>"
dashctl resolve blocker|question <id>
```

The aggregator polls every 5s by default (configurable in
`~/.claude-dashboard/config.json`), so give it a few seconds, then
reopen the popover -- that project's card should now be there.

### Reinstalling / updating after pulling new code

The LaunchAgent runs `.venv/bin/busy-bee` directly, not a frozen
build -- after pulling code changes, `launchctl unload` then
`scripts/install_launch_agent.sh` again (or just re-run
`./scripts/install.sh`) to pick them up. Dependency changes need
`pip install -e .` re-run first (part of `install.sh`).

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
        +--> Manual edits (resolve) -> written back into the central store directly
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
  cli.py              dashctl entrypoint
  project_store.py    per-project status.json read/write
  config.py           ~/.claude-dashboard/config.json handling
  process_utils.py    finds which terminal tty a dashctl call came from
  db.py                central SQLite schema + queries
  aggregator.py         polls project paths, merges into the central store
  terminal_launcher.py  osascript-driven click-to-resume / terminal reuse
  app.py                 rumps tray app + pywebview popover wiring
  global_setup.py         installs the CLAUDE.md snippet + Stop hook globally
  ui/                     popover.html/css/js
hooks/stop_hook.py     Claude Code Stop hook (the safety net)
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

## Tests

```
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```
