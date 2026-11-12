import datetime
import html
import json
import os
import threading
import uuid

import gradio as gr
from gradio import SelectData
from loguru import logger

from app_cmd.config.BuyConfig import BuyConfig
from tab.schedule import (
    build_schedule_rows,
    parse_start_time,
    resolve_start_times,
)
from tab.uploads import (
    build_upload_snapshot,
    normalize_uploaded_files,
    upload_count_text,
)
from tab.log import (
    refresh_task_panel,
    render_task_manager_panel,
    stop_all_running_tasks,
    visible_task_entries,
)
from task.buy import buy_new_terminal
from util import (
    ConfigDB,
    GlobalStatusInstance,
    LOG_DIR,
)
from util.Constant import (
    BEIJING_TZ,
    DEFAULT_MAX_LOG_FILES,
    DEFAULT_MAX_RUN_DIRS,
    DEFAULT_REQUEST_INTERVAL,
    GO_UPLOADED_FILES_STATE_KEY,
)
from util.proxy.ProxyManager import ProxyManager


def withTimeString(string):
    return (
        f"{datetime.datetime.now(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')}: {string}"
    )


def _build_task_log_path(filename: str) -> str:
    filename_only = os.path.splitext(os.path.basename(filename))[0]
    safe_name = "".join(
        ch if ch.isalnum() or ch in "-_." else "_" for ch in filename_only
    )
    safe_name = safe_name.strip("._") or "task"
    return os.path.join(LOG_DIR, f"{safe_name}_{uuid.uuid4().hex[:8]}.log")


def _build_task_proxy_list(
    proxy_string: str | None, *, include_direct: bool
) -> list[str]:
    proxies = ProxyManager.parse_proxy_list(proxy_string)
    proxies = [proxy for proxy in proxies if proxy.lower() != "none"]
    if include_direct:
        return ["none", *proxies]
    return proxies


def _parse_sale_start(value):
    return parse_start_time(value)


def _preview_value(value) -> str:
    if value in (None, "", []):
        return "-"
    if isinstance(value, list):
        return "、".join(str(item) for item in value) if value else "-"
    return str(value)


def _format_price_cents(value) -> str:
    try:
        amount = int(value)
    except (TypeError, ValueError):
        return _preview_value(value)
    return f"¥{amount / 100:.2f}"


def _format_buyer_identity(buyer_info) -> str:
    if not isinstance(buyer_info, list) or not buyer_info:
        return "-"

    id_type_map = {
        0: "身份证",
        1: "护照",
        2: "港澳居民来往内地通行证",
        3: "台湾居民来往大陆通行证",
        4: "外国人永久居留身份证",
    }
    items: list[str] = []
    for buyer in buyer_info:
        if not isinstance(buyer, dict):
            continue
        name = _preview_value(buyer.get("name"))
        id_type = id_type_map.get(buyer.get("id_type"), "未知证件")
        items.append(f"{name}（{id_type}）")
    return "、".join(items) if items else "-"


def _render_ticket_preview(config: dict) -> str:
    items = [
        ("账号", _preview_value(config.get("username"))),
        ("票数", _preview_value(config.get("count"))),
        ("单价", _format_price_cents(config.get("pay_money"))),
    ]
    item_html = "".join(
        (
            '<div class="btb-mini-card">'
            f"<strong>{html.escape(label)}</strong>"
            f"<span>{html.escape(value)}</span>"
            "</div>"
        )
        for label, value in items
    )
    return f"""
    <div class="btb-ticket-panel btb-ticket-panel--compact">
        <div class="btb-mini-grid btb-mini-grid--triple">{item_html}</div>
        <div class="btb-mini-card btb-ticket-panel__delivery">
            <strong>详细信息</strong>
            <span>{html.escape(_preview_value(config.get("detail") or "-"))}</span>
            <span>{html.escape(f"实名：{_format_buyer_identity(config.get('buyer_info'))}")}</span>
        </div>
    </div>
    """


def _get_saved_upload_snapshot():
    saved = GlobalStatusInstance.state_get("go.upload_snapshot")
    if saved is None:
        saved = ConfigDB.get("goUploadSnapshot")
    if saved is None:
        return build_upload_snapshot(
            GlobalStatusInstance.state_get_path_list(GO_UPLOADED_FILES_STATE_KEY)
        )
    return build_upload_snapshot(saved["files"], saved["rows"], saved["files"])


def _store_upload_snapshot(snapshot):
    GlobalStatusInstance.state_set("go.upload_snapshot", snapshot)
    ConfigDB.insert("goUploadSnapshot", snapshot)


def _get_session_upload_files() -> list[str]:
    return _get_saved_upload_snapshot()["files"]


def _file_ticket_preview(path):
    if path is None:
        return _render_ticket_preview({})
    try:
        with open(path, encoding="utf-8-sig") as file:
            content = json.load(file)
        if not isinstance(content, dict):
            raise ValueError("配置应是 JSON 对象")
        return _render_ticket_preview(content)
    except (OSError, ValueError) as exc:
        return f'<div class="btb-card-note">配置预览失败：{html.escape(str(exc))}</div>'


def go_start_tab():
    with gr.Column(elem_classes="btb-page-section"):
        with gr.Column(elem_classes="btb-card btb-card-sky btb-layout-card"):
            with gr.Row(elem_classes="!items-stretch !gap-3"):
                upload_ui = gr.Files(
                    label="抢票配置文件（同一文件重复上传只保留一份）",
                    file_types=[".json"],
                    file_count="multiple",
                    value=[],
                    scale=5,
                )
                with gr.Column(scale=4):
                    ticket_ui = gr.HTML(
                        value=_render_ticket_preview({}),
                        visible=True,
                    )
            upload_count_ui = gr.Markdown(
                upload_count_text({"files": [], "rows": [], "errors": []}),
                elem_id="btb-upload-count",
            )
            gr.Markdown(
                "### 每个配置的抢票开始时间\n"
                "时间均为北京时间（UTC+8）。双击最后一列可分别修改，格式为 "
                "`YYYY-MM-DD HH:MM:SS`，留空表示立即开始。\n"
                "新上传的配置默认使用各自的开售时间；修改只影响新启动的任务。"
            )
            schedule_paths = gr.State([])
            schedule_ui = gr.Dataframe(
                headers=["配置文件", "开售时间（北京时间）", "开始时间（可修改）"],
                datatype=["str", "str", "str"],
                type="array",
                value=[],
                interactive=True,
                static_columns=[0, 1],
                column_count=(3, "fixed"),
                row_count=(0, "fixed"),
                label="独立开始时间",
                elem_id="btb-task-schedule",
                wrap=True,
                column_widths=["44%", "28%", "28%"],
            )
            with gr.Row(elem_classes="!justify-end"):
                auto_fill_time_btn = gr.Button(
                    "按各自开售时间重置",
                    elem_classes="btb-soft-button",
                    scale=0,
                    min_width=220,
                )

        with gr.Row(elem_classes="btb-inline-actions !justify-end"):
            interval_ui = gr.Number(
                label="抢票间隔",
                value=None,
                minimum=1,
                info="默认抢票请求间隔（单位：毫秒）",
            )

    def sync_uploaded_files(files, rows, paths, *, force=False):
        snapshot = build_upload_snapshot(files, rows, paths)
        # Replace duplicate uploader entries as well as the schedule. Returning
        # skip for an unchanged uploader avoids a .change feedback loop.
        upload_update = (
            gr.update(value=snapshot["files"])
            if force or list(files or []) != snapshot["files"]
            else gr.skip()
        )
        _store_upload_snapshot(snapshot)
        GlobalStatusInstance.state_set_path_list(
            GO_UPLOADED_FILES_STATE_KEY, snapshot["files"]
        )
        if len(files or []) > len(snapshot["files"]):
            gr.Info(
                f"已忽略 {len(files) - len(snapshot['files'])} 次重复选择，同一文件只启动一个任务。"
            )
        return (
            upload_update,
            snapshot["rows"],
            snapshot["files"],
            upload_count_text(snapshot),
            _file_ticket_preview(snapshot["files"][0] if snapshot["files"] else None),
        )

    def reset_schedule(files):
        return sync_uploaded_files(files, [], [])

    def save_schedule(rows, paths):
        saved = GlobalStatusInstance.state_get("go.upload_snapshot")
        # An edit posted before a file deletion must not restore the old list.
        if not saved or paths != saved["files"] or len(rows or []) != len(paths):
            return
        if any(
            len(row) != 3 or row[0] != os.path.basename(path)
            for path, row in zip(paths, rows)
        ):
            return
        _store_upload_snapshot({**saved, "rows": rows})

    def file_select_handler(select_data: SelectData, files):
        index = select_data.index
        if not isinstance(index, int) or not files or not 0 <= index < len(files):
            return gr.skip()
        return _file_ticket_preview(files[index])

    def split_proxies(https_proxy_list: list[str], task_num: int) -> list[list[str]]:
        assigned_proxies: list[list[str]] = [[] for _ in range(task_num)]
        for i, proxy in enumerate(https_proxy_list):
            assigned_proxies[i % task_num].append(proxy)
        return assigned_proxies

    def launch_task(
        filename: str,
        *,
        config: BuyConfig,
        start_times: dict[str, str],
    ):
        with open(filename, "r", encoding="utf-8-sig") as file:
            content = file.read()
        filename_only = os.path.basename(filename)
        logger.info(f"启动 {filename_only}")
        log_file_path = _build_task_log_path(filename_only)
        logger.info(f"任务 {filename_only} 的日志文件：{log_file_path}")
        proc = buy_new_terminal(
            config=config.with_overrides(
                tickets_info=content, time_start=start_times[filename]
            ),
            log_file_path=log_file_path,
        )
        GlobalStatusInstance.register_task_log(
            title=filename_only,
            mode="终端",
            log_file=log_file_path,
            pid=proc.pid,
        )
        return proc

    def start_go(files, rows, paths, interval):
        if not files:
            gr.Warning("未提交抢票配置。")
            return gr.update(visible=False)

        try:
            if list(files) != normalize_uploaded_files(files):
                raise ValueError("正在移除重复配置，请等待上传列表同步后再开始。")
            # Validate every file before launching the first child process.
            build_schedule_rows(files)
            task_start_times = resolve_start_times(files, rows, paths)
        except ValueError as exc:
            raise gr.Error(str(exc)) from exc

        try:
            interval = int(interval)
        except (TypeError, ValueError):
            interval = DEFAULT_REQUEST_INTERVAL
        interval = max(1, interval)
        ConfigDB.insert("requestInterval", interval)

        https_proxys = ConfigDB.get("https_proxy") or ""
        include_direct_proxy = ConfigDB.get_as_bool("proxyIncludeDirect", True)
        https_proxy_list = _build_task_proxy_list(
            https_proxys,
            include_direct=include_direct_proxy,
        )
        if not https_proxy_list:
            gr.Warning("已关闭直连，请至少配置一个代理。")
            return gr.update(visible=False)
        assigned_proxies: list[list[str]] = []
        assigned_proxies_next_idx = 0
        # 从配置文件加载
        buy_config = BuyConfig.from_config_db(
            time_start="",
            interval=interval,
        )
        proxy_assignment_strategy = str(
            ConfigDB.get("proxyAssignmentStrategy") or "balanced"
        ).lower()
        if proxy_assignment_strategy not in {"balanced", "queue", "local_fanout"}:
            proxy_assignment_strategy = "balanced"
        queue_concurrency_limit = ConfigDB.get_as_int("queueConcurrencyLimit", 0)
        log_retention_days = buy_config.log_retention_days
        auto_cleanup_logs = ConfigDB.get("autoCleanupLogs")
        if auto_cleanup_logs is None:
            auto_cleanup_logs = True
        if auto_cleanup_logs:
            from util.Storage.CleanupUtil import cleanup_runtime_artifacts

            cleanup_runtime_artifacts(
                logs_dir=LOG_DIR,
                runs_dir=os.path.join(os.path.dirname(LOG_DIR), "btb_runs"),
                retention_days=log_retention_days,
                max_log_files=ConfigDB.get_as_int("maxLogFiles", DEFAULT_MAX_LOG_FILES),
                max_run_dirs=ConfigDB.get_as_int("maxRunDirs", DEFAULT_MAX_RUN_DIRS),
            )
        if proxy_assignment_strategy == "queue":
            worker_count = len(https_proxy_list)
            if queue_concurrency_limit > 0:
                worker_count = min(worker_count, queue_concurrency_limit)
            worker_count = max(1, min(worker_count, len(files)))
            pending_files = sorted(files, key=lambda path: task_start_times[path])
            pending_lock = threading.Lock()

            def queue_worker(proxy_slot: str):
                while True:
                    with pending_lock:
                        if not pending_files:
                            return
                        current_file = pending_files.pop(0)
                    try:
                        proc = launch_task(
                            current_file,
                            start_times=task_start_times,
                            config=buy_config.with_overrides(
                                https_proxys=proxy_slot,
                            ),
                        )
                        proc.wait()
                    except Exception as exc:
                        logger.exception(exc)

            for worker_idx in range(worker_count):
                threading.Thread(
                    target=queue_worker,
                    args=(https_proxy_list[worker_idx % len(https_proxy_list)],),
                    name=f"btb-queue-worker-{worker_idx + 1}",
                    daemon=True,
                ).start()
            gr.Info("抢票任务已按队列模式启动。")
            return gr.update(visible=True)

        if proxy_assignment_strategy == "local_fanout":
            fanout_proxy_pool = ",".join(https_proxy_list)
            for filename in files:
                launch_task(
                    filename,
                    start_times=task_start_times,
                    config=buy_config.with_overrides(
                        https_proxys=fanout_proxy_pool,
                        create_request_proxy_strategy="local_fanout",
                    ),
                )
            gr.Info("抢票任务已按代理池并发策略启动。")
            return gr.update(visible=True)

        for idx, filename in enumerate(files):
            if assigned_proxies == []:
                left_task_num = len(files) - idx
                assigned_proxies = split_proxies(https_proxy_list, left_task_num)
            launch_task(
                filename,
                start_times=task_start_times,
                config=buy_config.with_overrides(
                    https_proxys=",".join(assigned_proxies[assigned_proxies_next_idx]),
                ),
            )
            assigned_proxies_next_idx += 1
        gr.Info("抢票任务已启动，下面可以直接查看日志链接或停止任务。")
        return gr.update(visible=True)

    upload_outputs = [
        upload_ui,
        schedule_ui,
        schedule_paths,
        upload_count_ui,
        ticket_ui,
    ]
    # Exactly one writer for upload, delete and clear. All related callbacks
    # share a serial queue so older preview/clear events cannot restore files.
    upload_ui.change(
        fn=sync_uploaded_files,
        inputs=[upload_ui, schedule_ui, schedule_paths],
        outputs=upload_outputs,
        trigger_mode="always_last",
        concurrency_id="go-upload-state",
        concurrency_limit=1,
    )
    schedule_ui.input(
        fn=save_schedule,
        inputs=[schedule_ui, schedule_paths],
        outputs=None,
        trigger_mode="always_last",
        concurrency_id="go-upload-state",
        concurrency_limit=1,
    )
    upload_ui.select(file_select_handler, upload_ui, ticket_ui)

    with gr.Row(elem_classes="btb-inline-actions !justify-end"):
        stop_all_btn = gr.Button(
            "一键终止",
            variant="stop",
            elem_classes="btb-soft-button btb-stop-all-button",
            scale=0,
            min_width=120,
        )
        go_btn = gr.Button(
            "开始抢票",
            elem_classes="btb-strong-button",
            scale=0,
            min_width=140,
        )
    with gr.Column(
        visible=bool(visible_task_entries()),
        elem_classes="btb-card btb-card-sky btb-layout-card",
    ) as task_panel:
        task_refresh_token = render_task_manager_panel(task_panel)

    auto_fill_time_btn.click(
        fn=reset_schedule,
        inputs=upload_ui,
        outputs=upload_outputs,
        concurrency_id="go-upload-state",
        concurrency_limit=1,
    )

    go_btn.click(
        fn=start_go,
        inputs=[upload_ui, schedule_ui, schedule_paths, interval_ui],
        outputs=task_panel,
        concurrency_id="go-upload-state",
        concurrency_limit=1,
    ).then(
        fn=refresh_task_panel,
        inputs=None,
        outputs=[task_refresh_token, task_panel],
    )
    stop_all_btn.click(
        fn=stop_all_running_tasks,
        inputs=None,
        outputs=[task_refresh_token, task_panel],
    )

    def load_go_start_configs():
        snapshot = _get_saved_upload_snapshot()
        return (
            gr.update(
                value=ConfigDB.get_as_int("requestInterval", DEFAULT_REQUEST_INTERVAL)
            ),
            *sync_uploaded_files(
                snapshot["files"], snapshot["rows"], snapshot["files"], force=True
            ),
        )

    return (
        task_refresh_token,
        task_panel,
        load_go_start_configs,
        [interval_ui, *upload_outputs],
    )
