"""busy-bee menu bar app.

`rumps` owns the tray icon and app lifecycle; `pywebview` renders the
popover UI (busy_bee/ui/*). The aggregator runs on a background thread
inside this same process so the whole app is a single `busy-bee`
command to launch.

Known v1 limitation: rumps doesn't expose a way to bind a left-click on
the status item directly to an arbitrary handler without going through
its menu, so the tray icon shows a one-item menu ("Show Dashboard")
rather than opening the popover on a bare click. Functionally
equivalent, one extra click.
"""

from __future__ import annotations

import threading

import rumps
import webview

from busy_bee import aggregator, config, db, terminal_launcher

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
        terminal_launcher.resume_project(project["path"], cfg.get("terminal_app", "Terminal"))

    def resolve_item(self, item_id: int) -> bool:
        return db.resolve_item_by_id(item_id)

    def add_manual_item(self, project_name: str, item_type: str, text: str) -> int:
        return db.add_manual_item(project_name, item_type, text)


class BusyBeeApp(rumps.App):
    def __init__(self):
        super().__init__("busy-bee", title="🐝", menu=["Show Dashboard"])
        self.window: webview.Window | None = None
        self.api = Api()

    def _ensure_window(self) -> webview.Window:
        if self.window is None:
            self.window = webview.create_window(
                "busy-bee",
                url=f"{UI_DIR}/popover.html",
                js_api=self.api,
                width=360,
                height=480,
                frameless=True,
                easy_drag=False,
                on_top=True,
                hidden=True,
            )
        return self.window

    @rumps.clicked("Show Dashboard")
    def show_dashboard(self, _sender) -> None:
        window = self._ensure_window()
        window.show()
        window.evaluate_js("window.loadProjects && window.loadProjects()")

    def refresh_badge(self) -> None:
        count = db.count_all_unresolved_blockers_and_questions()
        self.title = f"🐝 🔴{count}" if count > 0 else "🐝"

    def start_badge_timer(self) -> None:
        def tick(_timer):
            self.refresh_badge()

        rumps.Timer(tick, 5).start()


def run_aggregator_thread() -> None:
    thread = threading.Thread(target=aggregator.run_forever, daemon=True)
    thread.start()


def main() -> None:
    db.init_db()
    run_aggregator_thread()

    app = BusyBeeApp()
    app.start_badge_timer()

    # pywebview needs its own loop; run it on a background thread and let
    # rumps (NSApplication) own the main thread, which macOS requires.
    webview_thread = threading.Thread(
        target=lambda: webview.start(gui="cocoa", debug=False), daemon=True
    )
    webview_thread.start()

    app.run()


if __name__ == "__main__":
    main()
