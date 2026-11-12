"""One canonical file list for the uploader, schedule and task launcher."""

import os

from tab.schedule import build_schedule_rows


def normalize_uploaded_files(files):
    unique = []
    seen = set()
    for path in files or []:
        path = os.fspath(path)
        identity = os.path.normcase(os.path.realpath(path))
        if identity not in seen:
            seen.add(identity)
            unique.append(path)
    return unique


def build_upload_snapshot(files, previous_rows=None, previous_paths=None):
    """Keep one row per unique full path, including explicitly marked bad files."""
    unique = normalize_uploaded_files(files)
    rows, errors = [], []
    for path in unique:
        try:
            rows.extend(build_schedule_rows([path], previous_rows, previous_paths))
        except ValueError as exc:
            rows.append([os.path.basename(path), "配置读取失败", ""])
            errors.append(str(exc))
    return {"files": unique, "rows": rows, "errors": errors}


def upload_count_text(snapshot):
    count = len(snapshot["files"])
    if snapshot["errors"]:
        return (
            f"已上传 **{count}** 个配置 · 时间表 **{len(snapshot['rows'])}** 行 · "
            f"**{len(snapshot['errors'])}** 个配置读取失败，请移除或修复后再启动。"
        )
    return (
        f"已上传 **{count}** 个配置 · 时间表 **{count}** 行 · 将启动 **{count}** 个任务"
    )
