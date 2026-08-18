from busy_bee import terminal_launcher as tl


class FakeResult:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def test_list_terminal_tabs_parses_osascript_output(monkeypatch):
    def fake_run(cmd, capture_output, text):
        return FakeResult(
            stdout="437|1|/dev/ttys001|busy-bee repo\n1226|2|/dev/ttys002|Terminal\n"
        )

    monkeypatch.setattr(tl.subprocess, "run", fake_run)
    tabs = tl._list_terminal_tabs()
    assert tabs == [
        {"window_id": "437", "tab_index": "1", "tty": "/dev/ttys001", "title": "busy-bee repo"},
        {"window_id": "1226", "tab_index": "2", "tty": "/dev/ttys002", "title": "Terminal"},
    ]


def test_list_terminal_tabs_skips_malformed_lines(monkeypatch):
    # A line missing a field (e.g. a mid-write race) shouldn't crash the
    # whole parse -- just drop that one line.
    monkeypatch.setattr(
        tl.subprocess, "run", lambda *a, **k: FakeResult(stdout="437|1|/dev/ttys001\n")
    )
    assert tl._list_terminal_tabs() == []


def test_session_title_for_tty_returns_custom_title(monkeypatch):
    monkeypatch.setattr(
        tl,
        "_find_tab_by_tty",
        lambda tty: {"window_id": "9", "tab_index": "2", "tty": "/dev/ttys002", "title": "busy-bee repo"},
    )
    assert tl.session_title_for_tty("ttys002") == "busy-bee repo"


def test_session_title_for_tty_none_when_tab_not_found(monkeypatch):
    monkeypatch.setattr(tl, "_find_tab_by_tty", lambda tty: None)
    assert tl.session_title_for_tty("ttys999") is None


def test_session_title_for_tty_strips_leading_status_glyph(monkeypatch):
    # Claude Code prefixes its auto-title with a busy/idle glyph
    # ("✳ Busy bee repo") that's redundant next to the dashboard's own
    # live-session dot.
    monkeypatch.setattr(
        tl,
        "_find_tab_by_tty",
        lambda tty: {"window_id": "9", "tab_index": "2", "tty": "/dev/ttys002", "title": "✳ Busy bee repo"},
    )
    assert tl.session_title_for_tty("ttys002") == "Busy bee repo"


def test_session_title_for_tty_none_for_untitled_shell(monkeypatch):
    # A plain shell with no Claude Code conversation defaults to
    # "Terminal" -- not a real name, so callers should get None and
    # fall back to something else rather than showing that literally.
    monkeypatch.setattr(
        tl,
        "_find_tab_by_tty",
        lambda tty: {"window_id": "9", "tab_index": "2", "tty": "/dev/ttys002", "title": "Terminal"},
    )
    assert tl.session_title_for_tty("ttys002") is None


def test_list_terminal_tabs_returns_empty_on_failure(monkeypatch):
    monkeypatch.setattr(tl.subprocess, "run", lambda *a, **k: FakeResult(returncode=1))
    assert tl._list_terminal_tabs() == []


def test_tty_has_live_claude_true_when_claude_attached(monkeypatch):
    monkeypatch.setattr(
        tl.subprocess, "run", lambda cmd, **k: FakeResult(stdout="-zsh\nclaude\n")
    )
    assert tl._tty_has_live_claude("ttys002") is True


def test_tty_has_live_claude_false_without_claude(monkeypatch):
    monkeypatch.setattr(tl.subprocess, "run", lambda cmd, **k: FakeResult(stdout="-zsh\n"))
    assert tl._tty_has_live_claude("ttys003") is False


def test_find_tab_by_tty_normalizes_dev_prefix(monkeypatch):
    monkeypatch.setattr(
        tl,
        "_list_terminal_tabs",
        lambda: [{"window_id": "9", "tab_index": "2", "tty": "/dev/ttys002"}],
    )
    assert tl._find_tab_by_tty("ttys002") == {
        "window_id": "9",
        "tab_index": "2",
        "tty": "/dev/ttys002",
    }
    assert tl._find_tab_by_tty("ttys999") is None


def test_resume_project_focuses_existing_session_when_tty_alive(monkeypatch):
    focused = {}
    monkeypatch.setattr(tl, "_tty_has_live_claude", lambda tty: True)
    monkeypatch.setattr(
        tl, "_find_tab_by_tty", lambda tty: {"window_id": "9", "tab_index": "2"}
    )
    monkeypatch.setattr(
        tl, "_focus_terminal_tab", lambda wid, idx: focused.update(window_id=wid, tab_index=idx)
    )

    def fail_if_called(cmd, **k):
        raise AssertionError("should not open a new window when a live session exists")

    monkeypatch.setattr(tl.subprocess, "run", fail_if_called)

    tl.resume_project("/Users/me/my-project", tty="ttys002")
    assert focused == {"window_id": "9", "tab_index": "2"}


def test_resume_project_opens_new_window_when_no_tty_recorded(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(tl.subprocess, "run", lambda cmd, **k: calls.append(cmd) or FakeResult())

    tl.resume_project(str(tmp_path), tty=None)
    assert len(calls) == 1
    assert calls[0][0] == "osascript"
    assert "claude --continue" in calls[0][2]


def test_resume_project_opens_new_window_when_tty_is_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(tl, "_tty_has_live_claude", lambda tty: False)

    def fail_if_focus_attempted(*a, **k):
        raise AssertionError("should not try to focus a dead tty")

    monkeypatch.setattr(tl, "_find_tab_by_tty", fail_if_focus_attempted)

    calls = []
    monkeypatch.setattr(tl.subprocess, "run", lambda cmd, **k: calls.append(cmd) or FakeResult())

    tl.resume_project(str(tmp_path), tty="ttys002")
    assert len(calls) == 1
    assert "claude --continue" in calls[0][2]


def test_resume_project_ignores_tty_for_iterm(tmp_path, monkeypatch):
    def fail_if_called(*a, **k):
        raise AssertionError("tty reuse detection is Terminal.app-only")

    monkeypatch.setattr(tl, "_tty_has_live_claude", fail_if_called)

    calls = []
    monkeypatch.setattr(tl.subprocess, "run", lambda cmd, **k: calls.append(cmd) or FakeResult())

    tl.resume_project(str(tmp_path), terminal_app="iTerm", tty="ttys002")
    assert len(calls) == 1
    assert "iTerm" in calls[0][2]


def test_hex_to_terminal_rgb_scales_to_16_bit():
    assert tl._hex_to_terminal_rgb("#ffffff") == (65535, 65535, 65535)
    assert tl._hex_to_terminal_rgb("#000000") == (0, 0, 0)
    assert tl._hex_to_terminal_rgb("#5b8def") == (0x5B * 257, 0x8D * 257, 0xEF * 257)


def test_color_tab_issues_applescript_with_scaled_rgb(monkeypatch):
    calls = []
    monkeypatch.setattr(tl.subprocess, "run", lambda cmd, **k: calls.append(cmd) or FakeResult())

    tl.color_tab("9", "2", "#000000")

    assert len(calls) == 1
    script = calls[0][2]
    assert "tab 2 of (first window whose id is 9)" in script
    assert "{0, 0, 0}" in script


def test_sync_session_colors_colors_each_live_tty_once(monkeypatch):
    tl._colored_ttys.clear()
    colored = []
    monkeypatch.setattr(tl, "_find_tab_by_tty", lambda tty: {"window_id": "9", "tab_index": "1"})
    monkeypatch.setattr(tl, "_system_is_dark_mode", lambda: False)
    monkeypatch.setattr(tl, "color_tab", lambda wid, idx, color: colored.append((wid, idx, color)))

    tl.sync_session_colors("my-project", ["ttys002"])
    tl.sync_session_colors("my-project", ["ttys002"])  # second call should no-op

    assert len(colored) == 1
    assert colored[0][:2] == ("9", "1")


def test_sync_session_colors_skips_ttys_with_no_matching_tab(monkeypatch):
    tl._colored_ttys.clear()
    colored = []
    monkeypatch.setattr(tl, "_find_tab_by_tty", lambda tty: None)
    monkeypatch.setattr(tl, "_system_is_dark_mode", lambda: False)
    monkeypatch.setattr(tl, "color_tab", lambda wid, idx, color: colored.append(color))

    tl.sync_session_colors("my-project", ["ttys999"])

    assert colored == []
    assert "ttys999" not in tl._colored_ttys


def test_sync_session_colors_uses_dark_variant_when_system_is_dark(monkeypatch):
    tl._colored_ttys.clear()
    colored = []
    monkeypatch.setattr(tl, "_find_tab_by_tty", lambda tty: {"window_id": "9", "tab_index": "1"})
    monkeypatch.setattr(tl, "_system_is_dark_mode", lambda: True)
    monkeypatch.setattr(tl, "color_tab", lambda wid, idx, color: colored.append(color))

    tl.sync_session_colors("my-project", ["ttys002"])

    assert colored == [tl.colors.terminal_background_color("my-project", dark=True)]


def test_system_is_dark_mode_true_when_defaults_reports_dark(monkeypatch):
    monkeypatch.setattr(tl.subprocess, "run", lambda *a, **k: FakeResult(stdout="Dark\n"))
    assert tl._system_is_dark_mode() is True


def test_system_is_dark_mode_false_when_key_is_unset(monkeypatch):
    # `defaults read` exits non-zero when the key doesn't exist at all
    # -- the normal state in light mode, since macOS only sets
    # AppleInterfaceStyle when dark mode is on.
    monkeypatch.setattr(tl.subprocess, "run", lambda *a, **k: FakeResult(returncode=1))
    assert tl._system_is_dark_mode() is False


def test_prune_colored_ttys_drops_dead_ttys():
    tl._colored_ttys.clear()
    tl._colored_ttys.update({"ttys001", "ttys002"})

    tl.prune_colored_ttys({"ttys001"})

    assert tl._colored_ttys == {"ttys001"}
