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
wires Claude Code up globally (step 3), and builds
`/Applications/Busy Bee.app` (step 4).

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

### 4. Launch the app

Launch **"Busy Bee"** from Spotlight (⌘Space, type "busy bee"),
Launchpad, or by double-clicking it in `/Applications`.

A few things to know before you conclude it isn't working:

- **It's a menu-bar-only app.** `LSUIElement=true` means no Dock icon
  and no window pop up on launch by design -- the only visible change
  is a small 🐝 icon appearing in the menu bar (top-right strip),
  easy to miss among other menu bar icons. Look there, not the Dock.
- **Relaunching an already-running instance looks identical to "didn't
  open."** Check first: `ps aux | grep busy-bee`. If it's already
  running, there's nothing more to launch -- just look for the icon.
- **Spotlight's search index can lag a few minutes after install**,
  even though the app is fully installed and working. This is a
  different system (`mds`, the OS's metadata index, not writable from
  a normal shell) from Launch Services (what Launchpad, the Dock, and
  double-click all use) -- `install.sh` updates Launch Services
  immediately, so Launchpad/Dock/double-click work right away even
  when Spotlight search hasn't caught up. If you don't want to wait:
  `open -R "/Applications/Busy Bee.app"` reveals it in Finder,
  draggable straight onto the Dock for permanent one-click access.
- **Launchpad is not the App Store.** Easy to mix up -- Launchpad
  shows installed apps as an icon grid (three-finger-and-thumb pinch
  on the trackpad, or F4 on some keyboards -- not universal, varies by
  Mac/keyboard); the App Store is a different app entirely for
  downloading things, and will never show a locally-built app.
- **A stray generic Python icon may appear in the Dock/Cmd+Tab
  anyway**, despite `LSUIElement`. This is a known, currently-unfixed
  packaging quirk -- see "Known limitations" below. The tray icon
  itself still works correctly regardless; this is cosmetic.

Click the 🐝 → "Show Dashboard" to open the popover. Click a project
name inside a card to open a terminal and resume that project's
Claude Code session (or focus the existing one, if it's already open
-- see Architecture).

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

`busy-bee` and `Busy Bee.app` both wrap `.venv`, not a frozen build --
after pulling changes, re-run `./scripts/install.sh` (or just
`scripts/build_app_bundle.sh` if only the app code changed, not
dependencies) and relaunch.

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
  install.sh              full install
  build_app_bundle.sh     builds/refreshes /Applications/Busy Bee.app
tests/
```

## Known limitations

- **Packaged `.app` has the wrong bundle identity.**
  `Contents/MacOS/BusyBee` `exec`s the venv's `busy-bee`, whose
  shebang resolves through Homebrew's Python framework, which itself
  re-execs into *its own* `Python.app` (needed for AppKit/PyObjC to
  get a valid WindowServer connection at all). Effect: macOS's
  process-launch layer registers the running process against
  `org.python.python`, not `dev.busybee.app` (confirmed via
  `lsappinfo list`: `bundleID="org.python.python"`,
  `type="Foreground"` instead of the `LSUIElement`-driven
  `UIElement`). Setting `__CFBundleIdentifier` in the launcher script
  (the trick tools like Platypus use) changes what
  `NSBundle.mainBundle()` reports *from inside* the process, but
  doesn't change how Launch Services classified it at launch --
  that's decided from the actual executable's own bundle before the
  env var is even read. The tray icon itself works fine regardless
  (status items don't require correct bundle branding), so this is
  cosmetic -- a stray generic Python icon in the Dock/Cmd+Tab, wrong
  name in Activity Monitor -- not functionally broken. Real fix would
  be building with `py2app` instead of a shell-script wrapper, since
  that embeds a private Python framework copy inside the bundle itself
  so there's no foreign bundle to get misattributed to. Not done yet.
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
