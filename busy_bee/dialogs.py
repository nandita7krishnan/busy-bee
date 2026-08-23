"""Native macOS dialogs used by the placeholder-project "Create
folder" flow -- kept out of app.py so its AppKit specifics stay in one
small, easily-monkeypatched place for tests.

Both functions here block the calling thread on a semaphore released
from the main AppKit run loop:

- Safe to call from an `Api` method. pywebview spawns a fresh thread
  per js_api call (see the note at app.py:229-234 about
  evaluate_js -- the same hazard applies here), so the wait never
  blocks the thread that would release it.
- Fatal to call from a rumps callback or anything already running on
  the main thread -- that thread would be waiting on itself.

`runModal()` (used by `confirm`) blocks the main run loop for its
duration, which pauses the rumps.Timer-driven 5s refresh (app.py:292)
while the dialog is up -- harmless, and arguably desirable here.
"""

from __future__ import annotations

from pathlib import Path

import webview


def choose_folder(window: webview.Window, initial: str | None = None) -> str | None:
    """Opens a native NSOpenPanel folder picker anchored to `window`.
    Returns the chosen absolute path, or None if the user cancelled.

    pywebview's `_file_name_semaphore` is per-window, so two concurrent
    folder dialogs on the same window would corrupt each other --
    callers must serialize this (Api.activate_placeholder_project holds
    a lock for exactly this reason) and disable the triggering UI
    control until the call returns.
    """
    result = window.create_file_dialog(
        webview.FileDialog.FOLDER, directory=initial or str(Path.home())
    )
    if not result:
        return None
    return result[0]


def confirm(message: str, informative: str, ok_title: str, cancel_title: str) -> bool:
    """A native NSAlert with custom button titles. Returns True if the
    user picked the `ok_title` button.

    Deliberately not pywebview's own `Window.create_confirmation_dialog`
    -- on the cocoa backend that ignores the `title` argument entirely
    and hardcodes localized "OK"/"Cancel" buttons, which would make the
    task-handoff question read as "OK / Cancel" instead of something
    like "Hand off to Claude / Keep in dashboard".
    """
    import AppKit
    from PyObjCTools import AppHelper

    from threading import Semaphore

    semaphore = Semaphore(0)
    response = {}

    def _run():
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(message)
        alert.setInformativeText_(informative)
        alert.addButtonWithTitle_(ok_title)
        alert.addButtonWithTitle_(cancel_title)
        result = alert.runModal()
        # NSAlertFirstButtonReturn == 1000, incrementing per button in
        # the order they were added.
        response["ok"] = result == 1000
        semaphore.release()

    AppHelper.callAfter(_run)
    semaphore.acquire()
    return response["ok"]
