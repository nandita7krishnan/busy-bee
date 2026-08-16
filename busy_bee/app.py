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

import threading
import time

import rumps
import webview
from PyObjCTools import AppHelper

from busy_bee import aggregator, config, db, icon, terminal_launcher

UI_DIR = __file__.rsplit("/", 1)[0] + "/ui"


class Api:
    """Exposed to the popover's JS as `window.pywebview.api`."""

    def get_projects(self) -> list[dict]:
        projects = db.get_projects()
        result = []
        for p in projects:
            done = [row["text"] for row in db.get_recent_done(p["name"])]
            todo = [row["text"] for row in db.get_next_todo(p["name"])]
            blockers = [
                {"id": row["id"], "text": row["text"]}
                for row in db.get_unresolved(p["name"], "blocker")
            ]
            questions = [
                {"id": row["id"], "text": row["text"]}
                for row in db.get_unresolved(p["name"], "question")
            ]
            result.append(
                {
                    "name": p["name"],
                    "path": p["path"],
                    "status": p["status"],
                    "done": done,
                    "todo": todo,
                    "blockers": blockers,
                    "questions": questions,
                }
            )
        return result

    def open_terminal(self, project_name: str) -> None:
        project = db.get_project(project_name)
        if project is None:
            return
        cfg = config.load_config()
        terminal_launcher.resume_project(
            project["path"], cfg.get("terminal_app", "Terminal"), tty=project["terminal_tty"]
        )

    def get_poll_interval_seconds(self) -> int:
        return config.load_config().get("poll_interval_seconds", 5)


class BusyBeeApp(rumps.App):
    def __init__(self, window: webview.Window):
        super().__init__("busy-bee", icon=str(icon.render_tray_icon(0)), menu=["Show Dashboard"])
        self.window = window

    @rumps.clicked("Show Dashboard")
    def show_dashboard(self, _sender) -> None:
        self.window.show()
        # evaluate_js() blocks its calling thread waiting on a semaphore
        # released from the main thread's run loop; since rumps.clicked
        # callbacks fire *on* the main thread, calling it here directly
        # would deadlock (main thread waits on itself). Run it from a
        # throwaway thread instead.
        threading.Thread(target=self._refresh_popover, daemon=True).start()

    def _refresh_popover(self) -> None:
        self.window.evaluate_js("window.loadProjects && window.loadProjects()")

    def refresh_badge(self) -> None:
        count = db.count_all_unresolved_blockers_and_questions()
        self.icon = str(icon.render_tray_icon(count))

        import AppKit

        AppKit.NSApp.dockTile().setBadgeLabel_(str(count) if count else None)
        AppKit.NSApp.dockTile().display()

    def start_badge_timer(self) -> None:
        def tick(_timer):
            self.refresh_badge()

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


def main() -> None:
    db.init_db()

    window = webview.create_window(
        "busy-bee",
        url=f"{UI_DIR}/popover.html",
        js_api=Api(),
        width=480,
        height=620,
        hidden=True,
    )

    def _hide_instead_of_close():
        window.hide()
        return False  # cancels the actual close -- see should_close() in
        # pywebview's cocoa backend: any False return from a `closing`
        # handler prevents the native window from closing at all.

    window.events.closing += _hide_instead_of_close

    app = BusyBeeApp(window)

    # pywebview requires the main thread for its blocking loop; this call
    # doesn't return until the app quits.
    webview.start(func=_on_webview_loop_started, args=(app,), gui="cocoa", debug=False)


if __name__ == "__main__":
    main()
