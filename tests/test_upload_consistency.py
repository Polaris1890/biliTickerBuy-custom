import json
import os

import pytest

from tab.uploads import build_upload_snapshot, normalize_uploaded_files


def ticket(tmp_path, name, **extra):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"sale_start": "2026-11-13 20:00:00", **extra}), encoding="utf-8"
    )
    return str(path)


def test_duplicate_upload_matches_screenshot(tmp_path):
    a, b, c = [ticket(tmp_path, f"{name}.json") for name in "abc"]
    snapshot = build_upload_snapshot([a, b, c, a])
    assert snapshot["files"] == [a, b, c]
    assert len(snapshot["rows"]) == 3
    assert snapshot["errors"] == []


def test_same_name_different_files_are_not_removed(tmp_path):
    a = ticket(tmp_path, "first/config.json", sku_id=1)
    b = ticket(tmp_path, "second/config.json", sku_id=2)
    snapshot = build_upload_snapshot([a, b])
    assert snapshot["files"] == [a, b]
    assert len(snapshot["rows"]) == 2


def test_equivalent_paths_are_deduplicated(tmp_path):
    a = ticket(tmp_path, "a.json")
    aliases = [a, os.path.join(str(tmp_path), ".", "a.json")]
    if os.name == "nt":
        aliases.append(a.upper())
    assert normalize_uploaded_files(aliases) == [a]


def test_invalid_file_does_not_leave_previous_extra_rows(tmp_path):
    a = ticket(tmp_path, "a.json")
    bad = tmp_path / "bad.json"
    bad.write_text("broken", encoding="utf-8")
    snapshot = build_upload_snapshot([a, str(bad)])
    assert len(snapshot["files"]) == len(snapshot["rows"]) == 2
    assert snapshot["rows"][1][1] == "配置读取失败"
    assert len(snapshot["errors"]) == 1


@pytest.fixture
def upload_demo(monkeypatch):
    import gradio as gr
    import tab.go as go
    from util import GlobalStatus

    monkeypatch.setattr(go, "GlobalStatusInstance", GlobalStatus())
    settings = {}
    monkeypatch.setattr(go.ConfigDB, "get", lambda key: settings.get(key))
    monkeypatch.setattr(
        go.ConfigDB, "insert", lambda key, value: settings.update({key: value})
    )
    with gr.Blocks(analytics_enabled=False) as demo:
        _, _, load, outputs = go.go_start_tab()
    functions = {fn.fn.__name__: fn.fn for fn in demo.fns.values() if fn.fn}
    return go, demo, functions, load, outputs


def test_add_duplicate_delete_clear_keep_all_views_equal(tmp_path, upload_demo):
    go, _, functions, _, _ = upload_demo
    a, b, c = [ticket(tmp_path, f"{name}.json") for name in "abc"]
    sync = functions["sync_uploaded_files"]
    _, rows, paths, count, _ = sync([a], [], [])
    rows[0][2] = "2026-11-13 19:59:59"
    _, rows, paths, count, _ = sync([a, b, c, a], rows, paths)
    assert len(paths) == len(rows) == 3
    assert "**3** 个配置" in count
    assert rows[0][2] == "2026-11-13 19:59:59"
    assert go._get_session_upload_files() == paths
    _, rows, paths, count, preview = sync([b, c], rows, paths)
    assert len(paths) == len(rows) == 2
    assert "**2** 个配置" in count
    assert go._get_session_upload_files() == paths
    _, rows, paths, count, preview = sync(None, rows, paths)
    assert rows == paths == go._get_session_upload_files() == []
    assert "**0** 个配置" in count
    assert "19:59:59" not in preview


def test_stale_table_edit_cannot_resurrect_deleted_file(tmp_path, upload_demo):
    go, _, functions, _, _ = upload_demo
    a, b = [ticket(tmp_path, f"{name}.json") for name in "ab"]
    _, old_rows, old_paths, _, _ = functions["sync_uploaded_files"]([a, b], [], [])
    functions["sync_uploaded_files"]([b], old_rows, old_paths)
    functions["save_schedule"](old_rows, old_paths)
    assert go._get_session_upload_files() == [b]
    assert len(go._get_saved_upload_snapshot()["rows"]) == 1


def test_refresh_restores_files_and_rows_from_one_snapshot(tmp_path, upload_demo):
    go, _, functions, load, outputs = upload_demo
    a = ticket(tmp_path, "a.json")
    b = ticket(tmp_path, "b.json")
    _, rows, paths, _, _ = functions["sync_uploaded_files"]([a, b, a], [], [])
    rows[0][2] = "2026-11-13 19:59:59"
    functions["save_schedule"](rows, paths)
    loaded = load()
    assert len(loaded) == len(outputs) == 6
    assert loaded[1]["value"] == [a, b]
    assert loaded[2] == rows
    assert loaded[3] == [a, b]
    assert "**2** 个配置" in loaded[4]
    # Restarting the app also restores the same deduplicated snapshot.
    go.GlobalStatusInstance.state_delete("go.upload_snapshot")
    restarted = load()
    assert restarted[1]["value"] == [a, b]
    assert restarted[2] == rows


def test_only_one_serial_writer_for_upload_delete_and_clear(upload_demo):
    _, demo, _, _, _ = upload_demo
    uploader = next(
        block
        for block in demo.blocks.values()
        if getattr(block, "file_count", None) == "multiple"
    )
    listeners = [
        dep
        for dep in demo.config["dependencies"]
        if any(target[0] == uploader._id for target in dep["targets"])
    ]
    assert all(
        target[1] not in {"upload", "clear", "delete"}
        for dep in listeners
        for target in dep["targets"]
    )
    writers = [
        dep
        for dep in listeners
        if any(target[1] == "change" for target in dep["targets"])
    ]
    assert len(writers) == 1
    fn = demo.fns[writers[0]["id"]]
    assert fn.concurrency_id == "go-upload-state"
    assert fn.concurrency_limit == 1


def test_duplicate_and_bad_json_block_start_before_any_task(
    tmp_path, upload_demo, monkeypatch
):
    import gradio as gr

    go, _, functions, _, _ = upload_demo
    a = ticket(tmp_path, "a.json")
    bad = tmp_path / "bad.json"
    bad.write_text("broken", encoding="utf-8")
    launched = []
    monkeypatch.setattr(
        go, "buy_new_terminal", lambda **kwargs: launched.append(kwargs)
    )
    for files in ([a, a], [a, str(bad)]):
        snapshot = build_upload_snapshot(files)
        with pytest.raises(gr.Error):
            functions["start_go"](files, snapshot["rows"], snapshot["files"], 1000)
        assert launched == []
