# 修改版安装与使用指南

版本：`2.15.18+schedule.2`，基于上游 `v2.15.18`。

本版本由个人维护，原项目为 [mikumifa/biliTickerBuy](https://github.com/mikumifa/biliTickerBuy)。源码和安装包遵循仓库内的 `LICENSE`（PolyForm Noncommercial 1.0.0），保留上游版权声明。

## Windows 安装

适用于 Windows 10 / 11、Intel 或 AMD 64 位电脑。

1. 打开 [本仓库 Releases](https://github.com/Polaris1890/biliTickerBuy-custom/releases)。公开版本可以直接下载，无需加入仓库或登录维护者账号。
2. 下载 `biliTickerBuy_custom_windows_amd64_v2.15.18-schedule.2.zip`，不要下载页面自动附带的 `Source code` 作为免安装程序。
3. 将 ZIP 完整解压到可写目录，例如 `D:\Apps\biliTickerBuy`。不要在 ZIP 压缩包内直接运行。
4. 双击 `biliTickerBuy.exe`。无需安装 Python；程序会打开浏览器，默认地址为 `http://127.0.0.1:7860/`，实际地址以程序窗口提示为准。
5. 保持程序窗口运行，关闭窗口会结束服务。第一次启动需要等待解压运行环境和加载界面。

安装包包含程序、安装说明和许可证，不包含任何账号、Cookie、购票人、收货地址、个人配置或日志。

## 首次使用

1. 在「账号登录」生成二维码，用 B 站手机客户端扫码并确认登录。
2. 提前在会员购添加实名购票人；需要邮寄的活动还需添加收货地址。
3. 在「生成配置」粘贴活动详情页链接，获取票务信息，选择日期、票档及购票人，填写联系人资料，生成并保存 JSON 配置。
4. 在「操作抢票」上传需要使用的 JSON 配置文件。
5. 核对数量提示：已上传的配置数、时间表行数应一致。同一文件重复选择只保留一份；同名但内容不同的文件会分别保留。
6. 时间表每一行对应一个配置，双击最后一列可单独修改开始时间，使用北京时间（UTC+8），格式为 `YYYY-MM-DD HH:MM:SS`。留空表示立即进入任务流程。
7. 「按各自开售时间重置」会将各行开始时间恢复为对应配置的开售时间。新设置仅影响之后启动的任务。
8. 核对账号、票档、购票人和时间后点击「开始抢票」。下单成功后，在订单链接、支付二维码或会员购待付款订单中手动完成支付。

保存的文件路径及开始时间会在刷新或重启后恢复。原配置文件必须仍然存在；移动目录、换电脑或清理临时文件后，需要重新上传配置。恢复文件列表不会自动启动抢票。

默认模式会分别启动任务；如果自行启用高级设置中的「队列」模式，任务还会受到队列并发上限限制。

## 更新已有安装

1. 先终止正在运行的任务并退出程序。
2. 备份原程序目录。
3. 在原目录中替换新版 `biliTickerBuy.exe`，保留自己的配置文件和数据。
4. 重新启动，核对登录状态、文件列表和开始时间，再手动启动任务。

请从本仓库的 Releases 获取修改版。上游更新程序下载的是上游版本，不能保证保留这些自定义功能。迁移到其他电脑时建议重新扫码登录并重新上传个人配置。

## 常见问题

- **网页没有自动打开：** 在浏览器打开程序窗口显示的本地地址，检查程序是否仍在运行。
- **7860 端口被占用：** 先关闭已运行的旧实例；或在终端执行 `biliTickerBuy.exe ui --port 7861`，再打开 `http://127.0.0.1:7861/`。
- **配置读取失败：** 上传「生成配置」导出的 JSON 文件；错误配置会保留为错误行，启动前必须移除或修复。
- **修改时间后任务仍使用旧时间：** 已运行的任务不会随表格变化而改变，请先停止对应任务，再按新时间启动。
- **系统提示文件来源不明：** 核对下载来自本仓库 Releases，并用附带的 SHA256 清单校验，不需要关闭系统安全软件。
- **下载后运行失败：** 确认系统为 Windows x64，并尝试在可写目录完整解压；保留终端错误信息用于排查。

## 源码安装（Python 3.11）

在仓库根目录打开 PowerShell：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe main.py ui
```

## 从源码构建 Windows EXE

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller==6.22.3
.\.venv\Scripts\python.exe -m PyInstaller main.spec
```

生成的程序位于 `dist\biliTickerBuy.exe`。也可以在本仓库 Actions 手动运行「Build custom Windows package」，从产物中下载 ZIP。该工作流只构建产物，不自动发布到 PyPI。

## 本次验证

36 项相关自动化测试通过，覆盖独立开始时间、重复上传、增删和清空配置、刷新恢复、无效配置阻止启动以及任务参数传递。另已通过浏览器验证重复选择同一文件、删除和清空场景；测试未提交真实购票订单。
