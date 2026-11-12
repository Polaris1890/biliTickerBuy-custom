import json
from types import SimpleNamespace

import pytest

from tab.schedule import build_schedule_rows, resolve_start_times


def write_ticket(tmp_path, name, sale_start):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sale_start": sale_start}), encoding="utf-8")
    return str(path)


@pytest.fixture
def tickets(tmp_path):
    return [
        write_ticket(tmp_path, "a.json", "2026-11-13 20:00:00"),
        write_ticket(tmp_path, "b.json", "2026-11-13 20:00:00"),
        write_ticket(tmp_path, "c.json", "2026-11-14 12:00:00"),
    ]


def test_three_configs_have_their_own_two_sale_times(tickets):
    rows = build_schedule_rows(tickets)
    times = resolve_start_times(tickets, rows, tickets)
    assert list(times.values()) == [
        "2026-11-13T20:00:00",
        "2026-11-13T20:00:00",
        "2026-11-14T12:00:00",
    ]


def test_edits_survive_reordering_removing_and_adding_same_name(tmp_path, tickets):
    rows = build_schedule_rows(tickets)
    rows[0][2] = "2026-11-13 19:59:59"
    another_a = write_ticket(tmp_path, "other/a.json", "2026-11-15 12:00:00")
    files = [tickets[2], another_a, tickets[0]]
    updated = build_schedule_rows(files, rows, tickets)
    assert [row[2] for row in updated] == [
        "2026-11-14 12:00:00",
        "2026-11-15 12:00:00",
        "2026-11-13 19:59:59",
    ]


def test_blank_means_immediate_and_minutes_are_accepted(tickets):
    rows = build_schedule_rows(tickets)
    rows[0][2] = ""
    rows[1][2] = "2026-11-13T19:59"
    times = resolve_start_times(tickets, rows, tickets)
    assert times[tickets[0]] == ""
    assert times[tickets[1]] == "2026-11-13T19:59:00"


def test_reset_restores_individual_sale_times(tickets):
    rows = build_schedule_rows(tickets)
    rows[0][2] = "2026-11-13 19:59:59"
    reset = build_schedule_rows(tickets)
    assert reset[0][2] == "2026-11-13 20:00:00"
    assert reset[2][2] == "2026-11-14 12:00:00"


@pytest.mark.parametrize("bad_value", ["tomorrow", "2026-02-30 20:00:00", 1000])
def test_invalid_time_is_rejected(tickets, bad_value):
    rows = build_schedule_rows(tickets)
    rows[2][2] = bad_value
    with pytest.raises(ValueError, match="c.json"):
        resolve_start_times(tickets, rows, tickets)


def test_stale_file_mapping_is_rejected(tickets):
    with pytest.raises(ValueError, match="列表已变化"):
        resolve_start_times(tickets[::-1], build_schedule_rows(tickets), tickets)


@pytest.mark.parametrize("strategy", ["balanced", "local_fanout", "queue"])
def test_actual_launcher_receives_each_time(monkeypatch, tmp_path, tickets, strategy):
    import gradio as gr
    import tab.go as go

    launched = []
    settings = {
        "proxyAssignmentStrategy": strategy,
        "proxyIncludeDirect": True,
        "autoCleanupLogs": False,
    }
    monkeypatch.setattr(go.ConfigDB, "get", lambda key: settings.get(key))
    monkeypatch.setattr(
        go.ConfigDB, "insert", lambda key, value: settings.update({key: value})
    )
    monkeypatch.setattr(
        go.ConfigDB,
        "get_as_bool",
        lambda key, default=False: settings.get(key, default),
    )
    monkeypatch.setattr(
        go.ConfigDB, "get_as_int", lambda key, default=0: settings.get(key, default)
    )

    def fake_launch(*, config, log_file_path):
        launched.append(config)
        return SimpleNamespace(pid=90000 + len(launched), wait=lambda: None)

    class ImmediateThread:
        def __init__(self, target, args=(), **kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(go, "buy_new_terminal", fake_launch)
    monkeypatch.setattr(
        go, "threading", SimpleNamespace(Thread=ImmediateThread, Lock=go.threading.Lock)
    )
    monkeypatch.setattr(
        go.GlobalStatusInstance, "register_task_log", lambda **kwargs: None
    )
    monkeypatch.setattr(go, "LOG_DIR", str(tmp_path))
    with gr.Blocks(analytics_enabled=False) as demo:
        go.go_start_tab()
    start = next(
        fn.fn for fn in demo.fns.values() if fn.fn and fn.fn.__name__ == "start_go"
    )
    rows = build_schedule_rows(tickets)
    rows[0][2] = "2026-11-13 19:59:59"
    start(tickets, rows, tickets, 1000)
    assert [config.time_start for config in launched] == [
        "2026-11-13T19:59:59",
        "2026-11-13T20:00:00",
        "2026-11-14T12:00:00",
    ]
    # A bad row must not launch even the earlier, valid rows.
    launched.clear()
    rows[2][2] = "bad"
    with pytest.raises(gr.Error):
        start(tickets, rows, tickets, 1000)
    assert launched == []
