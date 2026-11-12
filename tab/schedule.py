"""Per-file start times for the ticket task UI (all times are Beijing time)."""

import datetime
import json
import os


BEIJING_TZ = datetime.timezone(datetime.timedelta(hours=8))


def parse_start_time(value) -> datetime.datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.datetime.fromtimestamp(value, tz=BEIJING_TZ)
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(value, str) and value.strip():
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M",
        ):
            try:
                return datetime.datetime.strptime(value.strip(), fmt).replace(
                    tzinfo=BEIJING_TZ
                )
            except ValueError:
                pass
    return None


def build_schedule_rows(files, previous_rows=None, previous_paths=None):
    """Keep edits attached to full paths, even after adding/removing files."""
    previous = {
        path: row[2]
        for path, row in zip(previous_paths or [], previous_rows or [])
        if len(row) == 3
    }
    rows = []
    for path in files or []:
        try:
            with open(path, encoding="utf-8-sig") as file:
                config = json.load(file)
            sale_start = parse_start_time(
                config.get("sale_start", config.get("saleStart"))
            )
        except (OSError, ValueError, AttributeError) as exc:
            raise ValueError(
                f"无法读取配置 {os.path.basename(path)}，请检查 JSON 文件。"
            ) from exc
        sale_text = sale_start.strftime("%Y-%m-%d %H:%M:%S") if sale_start else ""
        rows.append(
            [
                os.path.basename(path),
                sale_text or "未提供",
                previous.get(path, sale_text),
            ]
        )
    return rows


def resolve_start_times(files, rows, row_paths):
    """Validate every row before launching any task; return canonical CLI times."""
    if list(files or []) != list(row_paths or []) or len(rows or []) != len(
        files or []
    ):
        raise ValueError("配置列表已变化，请等待时间表刷新后再开始。")
    resolved = {}
    for path, row in zip(files, rows):
        if len(row) != 3 or row[0] != os.path.basename(path):
            raise ValueError("时间表与配置不匹配，请重新上传配置。")
        value = row[2]
        if value is None or (isinstance(value, str) and not value.strip()):
            resolved[path] = ""
            continue
        start = parse_start_time(value) if isinstance(value, str) else None
        if start is None:
            raise ValueError(
                f"{os.path.basename(path)} 的开始时间无效，请填写 YYYY-MM-DD HH:MM:SS，或留空立即开始。"
            )
        resolved[path] = start.strftime("%Y-%m-%dT%H:%M:%S")
    return resolved
