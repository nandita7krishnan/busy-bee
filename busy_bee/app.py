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

import rumps
import webview
from PyObjCTools import AppHelper

from busy_bee import aggregator, config, db, icon, process_utils, terminal_launcher

UI_DIR = __file__.rsplit("/", 1)[0] + "/ui"


class Api:
    """Exposed to both the popover's and the floating widget's JS as
    `window.pywebview.api`. `popover_window` is set right after
    creation in main() -- Api needs to exist before the window does
    (it's passed as the window's js_api), so it can't be a constructor
    argument."""

    def __init__(self) -> None:
        self.popover_window: webview.Window | None = None

    def get_projects(self) -> list[dict]:
        projects = db.get_projects()
        live_ttys = process_utils.live_claude_ttys()
        result = []
        for p in projects:
            # A "session" only exists on the dashboard while its
            # terminal actually has a claude process running -- tied to
            # process state, not a time-since-last-log guess, so a
            # closed session's block disappears on the very next poll
            # instead of lingering.
            live_session_ttys = [t for t in db.get_project_ttys(p["name"]) if t in live_ttys]
            sessions = [
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
                        db.get_latest_summary_for_tty(p["name"], tty)
                        or terminal_launcher.session_title_for_tty(tty)
                        or tty
                    ),
                    "done": [row["text"] for row in db.get_recent_done(p["name"], terminal_tty=tty)],
                    "todo": [row["text"] for row in db.get_next_todo(p["name"], terminal_tty=tty)],
                }
                for tty in live_session_ttys
            ]

            if sessions:
                # Broken out per-session below instead -- a flat
                # cross-session list would interleave unrelated tasks
                # from two agents into one confusing feed.
                done, todo = [], []
            else:
                done = [row["text"] for row in db.get_recent_done(p["name"])]
                todo = [row["text"] for row in db.get_next_todo(p["name"])]

            blockers = [
                {"id": row["id"], "text": row["text"], "tty": row["terminal_tty"]}
                for row in db.get_unresolved(p["name"], "blocker")
            ]
            questions = [
                {"id": row["id"], "text": row["text"], "tty": row["terminal_tty"]}
                for row in db.get_unresolved(p["name"], "question")
            ]
            result.append(
                {
                    "name": p["name"],
                    "path": p["path"],
                    "status": p["status"],
                    "summary": p["last_summary"],
                    "done": done,
                    "todo": todo,
                    "sessions": sessions,
                    "blockers": blockers,
                    "questions": questions,
                }
            )
        return result

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
