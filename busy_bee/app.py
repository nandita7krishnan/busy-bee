"""busy-bee menu bar app.

`rumps` builds the tray icon/menu; `pywebview` renders the popover UI
(busy_bee/ui/*). Both are thin wrappers around the same singleton
NSApplication, and macOS only allows ONE thread to run its blocking
event loop (`NSApplication.run()`) -- whichever framework starts it
second either crashes (pywebview refuses off the main thread) or
deadlocks (rumps blocks forever on whatever thread calls it). Since
pywebview *requires* the main thread for `webview.start()`, that's the
one call allowed to block it. rumps' own loop-starting call
(`AppHelper.runEventLoop`, the last line of `App.run()`) is neutered
for the duration of that call so it just does its setup (status item,
menu, timers) and returns immediately; the already-running pywebview
loop then services the status item's events too, since it's the same
NSApplication under the hood. The rumps setup itself is scheduled onto
the main thread via `AppHelper.callAfter` once pywebview's loop is
live, which is the sanctioned way to touch AppKit objects from a
background thread in PyObjC.

The aggregator runs on its own background thread inside this same
process, so the whole app is a single `busy-bee` command to launch.

Known v1 limitation: rumps doesn't expose a way to bind a left-click on
the status item directly to an arbitrary handler without going through
its menu, so the tray icon shows a one-item menu ("Show Dashboard")
rather than opening the popover on a bare click. Functionally
equivalent, one extra click.
"""

from __future__ import annotations

import base64
import threading
import time
from pathlib import Path

import rumps
import webview
from PyObjCTools import AppHelper

from busy_bee import (
    aggregator,
    config,
    db,
    dialogs,
    icon,
    placeholder_store,
    process_utils,
    project_store,
    terminal_launcher,
    todo_sync,
)

UI_DIR = __file__.rsplit("/", 1)[0] + "/ui"


def _flag_belongs_to(flag: dict, tty: str, session_id: str | None) -> bool:
    """Is this unresolved blocker/question one the session currently
    running on `tty` logged? Falls back to matching the tty alone when
    either side has no session id -- items logged before session ids
    were tracked have none, and dropping them from their own session's
    card would be a worse regression than the stale-flag case this
    guards against."""
    if flag["tty"] != tty:
        return False
    if flag["session_id"] is None or session_id is None:
        return True
    return flag["session_id"] == session_id


class Api:
    """Exposed to both the popover's and the floating widget's JS as
    `window.pywebview.api`. `popover_window` is set right after
    creation in main() -- Api needs to exist before the window does
    (it's passed as the window's js_api), so it can't be a constructor
    argument."""

    def __init__(self) -> None:
        self.popover_window: webview.Window | None = None
        # Serializes the "Create folder" flow: it opens two sequential
        # native dialogs (a folder picker, maybe a confirm), and
        # pywebview's folder-dialog semaphore is per-window -- two
        # concurrent calls on the same window would corrupt each other.
        # The JS side also disables the triggering button for the same
        # reason (belt and suspenders).
        self._dialog_lock = threading.Lock()

    def get_projects(self) -> list[dict]:
        projects = db.get_projects()
        live_ttys = process_utils.live_claude_ttys()
        # A tty can appear in more than one project's history if a single
        # conversation `cd`'d from one tracked project to another without
        # the terminal itself closing -- current_project_by_tty() picks
        # the one it most recently logged to, so the session block moves
        # with it instead of lingering on every project it ever visited.
        # Passing each tty's current session start time also keeps a
        # *reused* tty from carrying its previous occupant's project
        # over to whatever unrelated session inherited the tty number.
        current_project_by_tty = db.current_project_by_tty(
            process_utils.claude_session_start_times()
        )
        last_activity = db.last_activity_by_project()
        result = []
        for p in projects:
            # A "session" only exists on the dashboard while its
            # terminal actually has a claude process running -- tied to
            # process state, not a time-since-last-log guess, so a
            # closed session's block disappears on the very next poll
            # instead of lingering.
            live_session_ttys = [
                t
                for t in db.get_project_ttys(p["name"])
                if t in live_ttys and current_project_by_tty.get(t) == p["name"]
            ]

            # A project's card now tracks "is someone actively working on
            # this right now", not "has this ever been logged to" -- the
            # same rule a session block already followed on its own. Skip
            # it entirely once its last terminal closes, rather than
            # leaving a stale card (with a now-meaningless "open" affordance
            # pointing at a dead terminal) sitting on the dashboard
            # indefinitely. Its history isn't lost -- it's still in the
            # db and reappears the moment a new session logs to it again.
            #
            # One carve-out: a project just activated from a placeholder
            # card (db.mark_project_activated, called at the end of
            # activate_placeholder_project) and that has never had a
            # dashctl item log a tty for it yet (terminal_tty IS NULL)
            # stays visible anyway -- otherwise the card the user just
            # created a folder for would vanish immediately, which is
            # the worst possible moment for that to happen. The instant
            # a real session logs something (terminal_tty becomes
            # non-NULL, via aggregator.sync_project), this carve-out
            # stops applying on its own and the ordinary rule above
            # takes back over.
            just_activated = p["activated_at"] is not None and p["terminal_tty"] is None
            if not live_session_ttys and not just_activated:
                continue

            # Fetched once per project, then split by tty below -- each
            # blocker/question already carries the tty that logged it,
            # so it can attach to that specific session's card instead
            # of the whole project. Anything whose tty isn't a currently
            # live session (no session block to attach to) falls back
            # to the project-level badge so it's never dropped.
            blockers_all = [
                {
                    "id": row["id"],
                    "text": row["text"],
                    "tty": row["terminal_tty"],
                    "session_id": row["session_id"],
                }
                for row in db.get_unresolved(p["name"], "blocker")
            ]
            questions_all = [
                {
                    "id": row["id"],
                    "text": row["text"],
                    "tty": row["terminal_tty"],
                    "session_id": row["session_id"],
                }
                for row in db.get_unresolved(p["name"], "question")
            ]

            # Which flags a session card claimed, so the project-level
            # fallback below is exactly "everything no live session card
            # is already showing" -- matching on tty alone would drop a
            # flag left behind by an earlier session on a *reused* tty,
            # since that tty is live but the flag isn't this session's.
            attached_flag_ids: set[int] = set()
            sessions = []
            for tty in live_session_ttys:
                # A tty is reused across unrelated `claude` invocations
                # in the same terminal window, so scope this session's
                # done/todo/summary by its actual session_id (the most
                # recent one logged to this tty) rather than the tty
                # alone -- otherwise a brand new session here would
                # inherit a previous, unrelated session's history.
                session_id = db.latest_session_id_for_tty(p["name"], tty)
                # Scoped by session_id for the same reason done/todo are:
                # an unresolved blocker or question logged by an earlier
                # session that happened to run on this same tty isn't
                # this session's to act on, and showing it here reads as
                # if the current agent is stuck on it.
                session_blockers = [b for b in blockers_all if _flag_belongs_to(b, tty, session_id)]
                session_questions = [
                    q for q in questions_all if _flag_belongs_to(q, tty, session_id)
                ]
                attached_flag_ids.update(f["id"] for f in session_blockers + session_questions)
                sessions.append(
                    {
                        "tty": tty,
                        # Prefer the agent's own `dashctl summary` for this
                        # session -- a far more useful label than "Session
                        # 1", and more accurate than Claude Code's
                        # auto-generated Terminal tab title, which is set
                        # once early on and often drifts from what the
                        # session ends up actually being about. Falls back
                        # to that tab title, then the tty itself, so the UI
                        # always has *some* stable per-session label.
                        "name": (
                            db.get_latest_summary_for_tty(p["name"], tty, session_id=session_id)
                            or terminal_launcher.session_title_for_tty(tty)
                            or tty
                        ),
                        "done": [
                            row["text"]
                            for row in db.get_recent_done(p["name"], terminal_tty=tty, session_id=session_id)
                        ],
                        "todo": [
                            row["text"]
                            for row in db.get_next_todo(p["name"], terminal_tty=tty, session_id=session_id)
                        ],
                        "blockers": session_blockers,
                        "questions": session_questions,
                    }
                )

            # Session-scoped done/todo stay broken out per-session (above)
            # rather than pooled here, to avoid interleaving unrelated
            # work from two agents into one confusing feed. What lands
            # here at the project level is specifically NOT session
            # work: items tagged source='human' -- today that means only
            # manually-added tasks migrated in from a placeholder project
            # on activation (see activate_placeholder_project). Tagged by
            # source, not by a null session_id/terminal_tty -- plenty of
            # ordinary agent items predate reliable tty/session tracking
            # and have both null too; filtering on those instead of
            # source leaked real agent history in here (see db.py's
            # get_unassigned_todos/done docstrings).
            # Plus, for a project that still has a *retained* placeholder
            # record (the user declined that handoff and kept the tasks
            # dashboard-only), those tasks too -- so a real project's
            # card never silently drops manual tasks depending on which
            # way that one-time prompt was answered.
            done = [{"id": row["id"], "text": row["text"]} for row in db.get_unassigned_done(p["name"])]
            todo = [{"id": row["id"], "text": row["text"]} for row in db.get_unassigned_todos(p["name"])]
            retained = placeholder_store.get(p["name"])
            if retained and retained["activated_path"] is not None:
                for task in retained["tasks"]:
                    entry = {"id": task["id"], "text": task["text"]}
                    (done if task["resolved_at"] else todo).append(entry)

            blockers = [b for b in blockers_all if b["id"] not in attached_flag_ids]
            questions = [q for q in questions_all if q["id"] not in attached_flag_ids]
            result.append(
                {
                    "name": p["name"],
                    "path": p["path"],
                    "status": p["status"],
                    "summary": p["last_summary"],
                    "placeholder": False,
                    # Allocated server-side (db.ensure_color_index) rather
                    # than hashed from the name in JS -- hashing gave two
                    # projects the same color. The UI just renders what
                    # it's told now.
                    "color": db.ensure_color_index(p["name"]),
                    # Most recent terminal activity, falling back to when
                    # the folder was created for a project activated from
                    # a placeholder that hasn't had a session yet. Sorted
                    # on below, then dropped -- the UI never sees it.
                    "_last_active": last_activity.get(p["name"]) or p["activated_at"] or "",
                    "done": done,
                    "todo": todo,
                    "sessions": sessions,
                    "blockers": blockers,
                    "questions": questions,
                }
            )

        result.extend(self._placeholder_cards())
        # Most recently worked-in first. ISO8601 UTC strings throughout,
        # so a plain string comparison is already chronological.
        result.sort(key=lambda card: card["_last_active"], reverse=True)
        for card in result:
            del card["_last_active"]
        return result

    def _placeholder_cards(self) -> list[dict]:
        cards = []
        for record in placeholder_store.list_pending():
            resolved = [t for t in record["tasks"] if t["resolved_at"]]
            unresolved = [t for t in record["tasks"] if not t["resolved_at"]]
            resolved.sort(key=lambda t: t["created_at"], reverse=True)
            cards.append(
                {
                    "name": record["name"],
                    "path": None,
                    "status": "idle",
                    "summary": None,
                    "placeholder": True,
                    # Allocates + persists on first use, which also
                    # backfills records that predate color_index --
                    # defaulting those to 0 collided with whichever real
                    # project already had slot 0.
                    "color": placeholder_store.ensure_color_index(record["name"]),
                    # A placeholder has no terminal, so "last touched" is
                    # the last time the user typed into it here -- which
                    # keeps a just-created card at the top, where they're
                    # looking, rather than sinking it below every project
                    # with a live session.
                    "_last_active": max(
                        [record["created_at"]] + [t["created_at"] for t in record["tasks"]]
                    ),
                    "done": [{"id": t["id"], "text": t["text"]} for t in resolved[:5]],
                    "todo": [{"id": t["id"], "text": t["text"]} for t in unresolved],
                    "sessions": [],
                    "blockers": [],
                    "questions": [],
                }
            )
        return cards

    def add_placeholder_project(self, name: str) -> dict:
        try:
            placeholder_store.create(name)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "name": name}

    def remove_placeholder_project(self, project_name: str) -> dict:
        # dashctl untrack only reaches config.json + the sqlite store
        # (cli.cmd_untrack), so without this a mistyped placeholder card
        # would otherwise be permanently stuck with no way to remove it.
        return {"ok": placeholder_store.delete(project_name)}

    def add_placeholder_task(self, project_name: str, text: str) -> dict:
        try:
            task = placeholder_store.add_task(project_name, text)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "task": task}

    def set_placeholder_task_done(self, project_name: str, task_id: str, done: bool) -> dict:
        return {"ok": placeholder_store.set_task_resolved(project_name, task_id, done)}

    def activate_placeholder_project(self, project_name: str) -> dict:
        """The "Create folder" flow -- turns a placeholder card into a real,
        folder-backed project. Runs the whole sequence under
        _dialog_lock -- it drives up to two sequential native dialogs on
        the same window, and pywebview's folder-dialog semaphore is
        per-window, so a second concurrent call here would corrupt the
        first's wait."""
        with self._dialog_lock:
            record = placeholder_store.get(project_name)
            if record is None or record["activated_path"] is not None:
                return {"ok": False, "error": "no such placeholder project"}

            if self.popover_window is None:
                return {"ok": False, "error": "no window to anchor the folder picker to"}
            parent = dialogs.choose_folder(self.popover_window)
            if not parent:
                return {"ok": False, "cancelled": True}

            target = Path(parent) / project_name

            # Re-checked here, not just at placeholder_store.create() time
            # -- config.auto_register can claim this exact name from any
            # terminal in the interim between the card being created and
            # "Create folder" being clicked.
            tracked_names = {p["name"] for p in config.list_projects()}
            tracked_paths = {p["path"] for p in config.list_projects()}
            if project_name in tracked_names or str(target) in tracked_paths:
                return {"ok": False, "error": f"{project_name!r} is already a tracked project"}

            if target.exists():
                if target.is_dir() and not any(target.iterdir()):
                    pass  # adopt the empty directory
                else:
                    return {"ok": False, "error": f"{target} already exists and isn't empty"}
            else:
                try:
                    target.mkdir(parents=True)
                except OSError as exc:
                    return {"ok": False, "error": str(exc)}

            unresolved = [t for t in record["tasks"] if not t["resolved_at"]]
            handed_off = False
            if unresolved:
                handed_off = dialogs.confirm(
                    f'Hand off "{project_name}" tasks to Claude?',
                    f"{len(unresolved)} task(s) will be added to {target} as todo items "
                    "so a Claude session started there sees them immediately. "
                    "Declining keeps them here on the dashboard instead.",
                    "Hand off to Claude",
                    "Keep in dashboard",
                )

            status_path = config.project_status_path(target)
            status_path.parent.mkdir(parents=True, exist_ok=True)
            if not status_path.exists():
                status_path.write_text("[]")

            migrated = 0
            if handed_off:
                migrated = self._migrate_tasks(target, record["tasks"])

            config.add_project(project_name, str(target))
            db.upsert_project(project_name, str(target))
            db.mark_project_activated(project_name)

            if handed_off or not record["tasks"]:
                # Handed off -> the tasks now live in status.json, this
                # record's job is done. No tasks ever added -> nothing
                # for a retained record to usefully carry, so don't
                # leave an empty stub behind in placeholders.json.
                placeholder_store.delete(project_name)
            else:
                placeholder_store.mark_activated(project_name, str(target))

            # Handing off means "Claude takes it from here", so open the
            # terminal and give it an actual opening prompt rather than
            # leaving the user to start the session themselves. The
            # SessionStart hook's additionalContext alone isn't enough --
            # it does inject the task list, but Claude Code takes no turn
            # until a message arrives, so the agent would sit silently
            # knowing about the tasks and never bring them up.
            if handed_off:
                cfg = config.load_config()
                terminal_launcher.resume_project(
                    str(target),
                    cfg.get("terminal_app", "Terminal"),
                    prompt=self._handoff_prompt(unresolved),
                )

            return {
                "ok": True,
                "path": str(target),
                "migrated": migrated,
                "handed_off": handed_off,
            }

    @staticmethod
    def _handoff_prompt(tasks: list[dict]) -> str:
        lines = "\n".join(f"- [{t['id']}] {t['text']}" for t in tasks)
        return (
            "I queued these tasks on my busy-bee dashboard before this "
            f"project existed:\n{lines}\n\n"
            "Give me a one-line plan for each, then ask which to start "
            "with -- don't start changing things yet. As each one gets "
            "done, run `dashctl resolve todo <id>` with the id in "
            "brackets so it clears off my dashboard."
        )

    @staticmethod
    def _migrate_tasks(target: Path, tasks: list[dict]) -> int:
        """Writes a placeholder's tasks straight into the new project's
        status.json, bypassing project_store.add_item -- that
        unconditionally stamps process_utils.find_claude_ancestor_tty()/
        current_session_id() (project_store.py:59-60), which would
        misattribute these manual items to whatever session happens to
        be running busy-bee itself. terminal_tty/session_id are forced
        None instead, and source is "human" -- a zero-migration
        distinction (items.source has no CHECK constraint, db.py:27) that
        nothing else branches on today. Original created_at is kept
        (not "now") so a migrated item can't accidentally satisfy the
        Stop hook's has_logged_this_turn recency window for an unrelated,
        concurrent agent turn."""
        items = project_store.all_items(target)
        for task in tasks:
            items.append(
                {
                    "id": task["id"],
                    "type": "done" if task["resolved_at"] else "todo",
                    "text": task["text"],
                    "created_at": task["created_at"],
                    "resolved_at": task["resolved_at"],
                    "source": "human",
                    "terminal_tty": None,
                    "session_id": None,
                }
            )
        project_store._save(target, items)
        todo_sync.seed_state(target, [t["text"] for t in tasks])
        return len(tasks)

    def open_terminal(self, project_name: str, tty: str | None = None) -> None:
        project = db.get_project(project_name)
        if project is None:
            return
        cfg = config.load_config()
        terminal_launcher.resume_project(
            project["path"], cfg.get("terminal_app", "Terminal"), tty=tty or project["terminal_tty"]
        )

    def open_dashboard(self) -> None:
        """Shows the popover and refreshes its content. Called by the
        floating widget's click handler, and by the tray menu's "Show
        Dashboard" (BusyBeeApp.show_dashboard delegates here so both
        entry points share one code path)."""
        if self.popover_window is None:
            return
        self.popover_window.show()
        threading.Thread(target=self.refresh_popover_content, daemon=True).start()

    def refresh_popover_content(self) -> None:
        # evaluate_js() blocks its calling thread waiting on a semaphore
        # released from the main thread's run loop; if called from the
        # main thread (e.g. a rumps.clicked callback, which already
        # runs there) that's the thread waiting on itself -- a
        # deadlock, not just slowness. Always call this from a
        # throwaway background thread.
        if self.popover_window is not None:
            self.popover_window.evaluate_js("window.loadProjects && window.loadProjects()")

    def get_widget_icon_data_uri(self) -> str:
        # A data: URI, not a file path -- widget.html is served over
        # http://127.0.0.1 by pywebview's local server (any bare
        # filesystem path passed as a window's url goes through that,
        # not file://), and WKWebView silently blocks an http:// page
        # from loading a file:// resource. Confirmed live: the <img>
        # naturalWidth/Height stayed 0x0 with a file:// src despite the
        # file genuinely existing. data: URIs aren't subject to that
        # origin restriction.
        count = db.count_all_unresolved_blockers_and_questions()
        # Kept proportional to WIDGET_SIZE, plus the same ~1.33x
        # headroom the original 128-for-96 ratio had for a crisp,
        # non-blurry render at the window's actual size.
        path = icon.render_widget_icon(count, size=326)
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{encoded}"


class BusyBeeApp(rumps.App):
    def __init__(self, api: Api, widget_window: webview.Window):
        super().__init__("busy-bee", icon=str(icon.render_tray_icon(0)), menu=["Show Dashboard"])
        self.api = api
        self.widget_window = widget_window

    @rumps.clicked("Show Dashboard")
    def show_dashboard(self, _sender) -> None:
        self.api.open_dashboard()

    def refresh_badge(self) -> None:
        count = db.count_all_unresolved_blockers_and_questions()
        self.icon = str(icon.render_tray_icon(count))

        import AppKit

        AppKit.NSApp.dockTile().setBadgeLabel_(str(count) if count else None)
        AppKit.NSApp.dockTile().display()

    def _refresh_widget_icon(self) -> None:
        self.widget_window.evaluate_js("window.refreshIcon && window.refreshIcon()")

    def start_badge_timer(self) -> None:
        # Also drives the popover's and widget's periodic refresh, not
        # just the badge -- a JS-side setInterval was tried first for
        # the popover and turned out unreliable in practice (confirmed
        # live: the badge count, driven by this same rumps.Timer, kept
        # updating correctly the whole time, while the popover's own
        # timer silently stopped refreshing). Piggybacking on this
        # already-proven-reliable Python-side timer instead of
        # trusting another opaque JS one for the widget too.
        def tick(_timer):
            self.refresh_badge()
            threading.Thread(target=self.api.refresh_popover_content, daemon=True).start()
            threading.Thread(target=self._refresh_widget_icon, daemon=True).start()

        rumps.Timer(tick, 5).start()


def run_aggregator_thread() -> None:
    thread = threading.Thread(target=aggregator.run_forever, daemon=True)
    thread.start()


def _start_rumps_setup_without_blocking(app: BusyBeeApp) -> None:
    """Runs rumps' real App.run() setup (status item, menu, timers) but
    without its final blocking call -- pywebview's loop, already running
    on the main thread by the time this fires, services those events
    instead. See module docstring for why this is necessary."""
    original_run_event_loop = AppHelper.runEventLoop
    AppHelper.runEventLoop = lambda *args, **kwargs: None
    try:
        app.run()
    finally:
        AppHelper.runEventLoop = original_run_event_loop

    import AppKit

    # Gives busy-bee an actual Dock icon (previously accessory-only/
    # no Dock presence) using the same bee art, with macOS's own
    # native badge widget -- set explicitly here rather than relying
    # on Info.plist's LSUIElement, since the packaged .app's bundle
    # identity doesn't reliably apply to this process anyway (see
    # README's Known limitations).
    AppKit.NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
    dock_image = AppKit.NSImage.alloc().initWithContentsOfFile_(str(icon.render_plain_bee()))
    AppKit.NSApp.setApplicationIconImage_(dock_image)

    app.start_badge_timer()
    app.refresh_badge()


def _on_webview_loop_started(app: BusyBeeApp) -> None:
    """Runs on a background thread spawned by webview.start(); dispatches
    the actual AppKit setup back onto the main thread, which is the
    PyObjC-sanctioned way to touch AppKit objects from off-thread.

    Waits a couple seconds before creating the status item, as cheap
    insurance against creating it concurrently with pywebview's own
    WKWebView/WebKit XPC setup -- both touch Control Center's
    status-item scene-connection machinery. This turned out not to be
    the main cause of status items failing to appear (that was
    launching via Launch Services at all -- see README's Known
    limitations, fixed by running this as a launchd agent instead of a
    double-clickable .app), but it's a low-cost precaution and was
    present during working runs, so it stays.
    """
    run_aggregator_thread()
    time.sleep(2)
    AppHelper.callAfter(_start_rumps_setup_without_blocking, app)


WIDGET_SIZE = 245  # 3x the original 96, then -15% on request (the 3x pass ran a bit too large)


def main() -> None:
    db.init_db()

    api = Api()

    # Must be windows[0] (the first window created): webview.start()
    # blocks the main thread on this one specifically, and waits for
    # its `shown` event (fired regardless of `hidden`) before creating
    # any additional windows -- so this has to come before the widget.
    popover_window = webview.create_window(
        "busy-bee",
        url=f"{UI_DIR}/popover.html",
        js_api=api,
        width=480,
        height=620,
        hidden=True,
    )
    api.popover_window = popover_window

    def _hide_instead_of_close():
        popover_window.hide()
        return False  # cancels the actual close -- see should_close() in
        # pywebview's cocoa backend: any False return from a `closing`
        # handler prevents the native window from closing at all.

    popover_window.events.closing += _hide_instead_of_close

    # The floating widget: a small always-on-top, frameless, transparent
    # window showing just the bee icon (same art + badge as the tray
    # icon). Draggable via easy_drag (native cocoa mouseDown/mouseDragged
    # handling -- a plain click still reaches the page's JS click
    # handler normally; only an actual drag moves the window). Visible
    # by default, unlike the popover -- the whole point is an
    # always-there click target.
    widget_window = webview.create_window(
        "busy-bee-widget",
        url=f"{UI_DIR}/widget.html",
        js_api=api,
        width=WIDGET_SIZE,
        height=WIDGET_SIZE,
        frameless=True,
        easy_drag=True,
        on_top=True,
        transparent=True,
        resizable=False,
        hidden=False,
    )

    app = BusyBeeApp(api, widget_window)

    # pywebview requires the main thread for its blocking loop; this call
    # doesn't return until the app quits.
    webview.start(func=_on_webview_loop_started, args=(app,), gui="cocoa", debug=False)


if __name__ == "__main__":
    main()
