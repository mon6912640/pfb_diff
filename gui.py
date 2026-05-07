#!/usr/bin/env python3
"""PfbDiff NiceGUI Desktop App — 暗色主题树形对比工具"""

import os
import time
import webbrowser
import tempfile
from pathlib import Path

from nicegui import ui, app

from diff_engine import diff_prefabs
from report_html_tree import write_html_report as write_tree_report
from report_json import write_json_report
from prefab_parser import parse_prefab

# ── 常量 ──
REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")


# ── 状态 ──
class AppState:
    def __init__(self):
        self.before_file: str | None = None
        self.after_file: str | None = None
        self.before_name: str = ""
        self.after_name: str = ""
        self.last_report_html: str | None = None
        self.last_report_json: str | None = None
        self.is_generating: bool = False


state = AppState()


# ── 工具函数 ──
def _ensure_reports_dir() -> None:
    if not os.path.isdir(REPORTS_DIR):
        os.makedirs(REPORTS_DIR)


def _safe_name(name: str) -> str:
    base = os.path.basename(name)
    if base.endswith(".prefab"):
        base = base[:-7]
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in base) or "prefab"


def _default_report_paths(before_name: str, after_name: str):
    _ensure_reports_dir()
    bn = _safe_name(before_name)
    an = _safe_name(after_name)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = f"{bn}__to__{an}_{stamp}" if bn != an else f"{bn}_diff_{stamp}"
    return {
        "html": os.path.join(REPORTS_DIR, base + ".html"),
        "json": os.path.join(REPORTS_DIR, base + ".json"),
    }


def _parse_info(file_path: str):
    try:
        doc = parse_prefab(file_path)
        return {
            "ok": True,
            "node_count": len(doc.nodes),
            "root_name": doc.root_nodes[0].name if doc.root_nodes else "",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _list_recent_reports(limit: int = 10):
    _ensure_reports_dir()
    files = []
    for f in os.listdir(REPORTS_DIR):
        if f.endswith(".html"):
            p = os.path.join(REPORTS_DIR, f)
            files.append((p, os.path.getmtime(p)))
    files.sort(key=lambda x: x[1], reverse=True)
    return [p for p, _ in files[:limit]]


# ── 事件处理 ──
async def handle_before_upload(e):
    suffix = os.path.splitext(e.file.name)[1] or ".prefab"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="pfb_before_") as f:
        f.write(await e.file.read())
        state.before_file = f.name
    state.before_name = e.file.name
    before_zone.refresh()
    check_ready()


async def handle_after_upload(e):
    suffix = os.path.splitext(e.file.name)[1] or ".prefab"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="pfb_after_") as f:
        f.write(await e.file.read())
        state.after_file = f.name
    state.after_name = e.file.name
    after_zone.refresh()
    check_ready()


def remove_before():
    if state.before_file and os.path.exists(state.before_file):
        try:
            os.remove(state.before_file)
        except OSError:
            pass
    state.before_file = None
    state.before_name = ""
    before_zone.refresh()
    check_ready()


def remove_after():
    if state.after_file and os.path.exists(state.after_file):
        try:
            os.remove(state.after_file)
        except OSError:
            pass
    state.after_file = None
    state.after_name = ""
    after_zone.refresh()
    check_ready()


# ── UI 元素引用 ──
gen_btn = None
view_btn = None
status_label = None


# ── 动态刷新组件 ──
@ui.refreshable
def before_zone():
    with ui.card().classes("w-full").style("min-height: 200px; background: #111827; border: 2px dashed #334155; border-radius: 8px;"):
        with ui.row().classes("w-full items-center gap-1 mb-2"):
            ui.icon("arrow_back", size="14px").classes("text-gray-500")
            ui.label("旧版本 (Before)").classes("text-gray-500 text-xs font-bold uppercase tracking-wider")

        if state.before_file:
            info = _parse_info(state.before_file)
            with ui.column().classes("w-full px-2 pb-2"):
                with ui.row().classes("w-full items-center justify-between"):
                    with ui.column().classes("gap-0"):
                        ui.label(state.before_name).classes("text-white font-medium text-sm")
                        if info["ok"]:
                            ui.label(f"📄 {info['node_count']} 节点").classes("text-gray-400 text-xs mt-1")
                        else:
                            ui.label(f"⚠️ 解析失败: {info['error']}").classes("text-red-400 text-xs mt-1")
                    ui.button("🗑 移除", on_click=remove_before).props("flat dense").classes("text-gray-500 hover:text-red-400 text-xs")
                ui.upload(on_upload=handle_before_upload, auto_upload=True, label="").props("accept=.prefab flat bordered").classes("w-full mt-2")
        else:
            with ui.column().classes("w-full items-center justify-center py-8"):
                ui.icon("upload_file", size="40px").classes("text-gray-600 mb-2")
                ui.label("拖入旧版本 .prefab").classes("text-gray-400 text-sm")
                ui.label("或点击选择文件").classes("text-gray-600 text-xs mt-1")
                ui.upload(on_upload=handle_before_upload, auto_upload=True, label="").props("accept=.prefab flat bordered").classes("w-full mt-3")


@ui.refreshable
def after_zone():
    with ui.card().classes("w-full").style("min-height: 200px; background: #111827; border: 2px dashed #334155; border-radius: 8px;"):
        with ui.row().classes("w-full items-center gap-1 mb-2"):
            ui.icon("arrow_forward", size="14px").classes("text-gray-500")
            ui.label("新版本 (After)").classes("text-gray-500 text-xs font-bold uppercase tracking-wider")

        if state.after_file:
            info = _parse_info(state.after_file)
            with ui.column().classes("w-full px-2 pb-2"):
                with ui.row().classes("w-full items-center justify-between"):
                    with ui.column().classes("gap-0"):
                        ui.label(state.after_name).classes("text-white font-medium text-sm")
                        if info["ok"]:
                            ui.label(f"📄 {info['node_count']} 节点").classes("text-gray-400 text-xs mt-1")
                        else:
                            ui.label(f"⚠️ 解析失败: {info['error']}").classes("text-red-400 text-xs mt-1")
                    ui.button("🗑 移除", on_click=remove_after).props("flat dense").classes("text-gray-500 hover:text-red-400 text-xs")
                ui.upload(on_upload=handle_after_upload, auto_upload=True, label="").props("accept=.prefab flat bordered").classes("w-full mt-2")
        else:
            with ui.column().classes("w-full items-center justify-center py-8"):
                ui.icon("upload_file", size="40px").classes("text-gray-600 mb-2")
                ui.label("拖入新版本 .prefab").classes("text-gray-400 text-sm")
                ui.label("或点击选择文件").classes("text-gray-600 text-xs mt-1")
                ui.upload(on_upload=handle_after_upload, auto_upload=True, label="").props("accept=.prefab flat bordered").classes("w-full mt-3")


@ui.refreshable
def stats_summary(result):
    container = ui.context.client.layout.default_slot.children[-1] if False else None
    if not result:
        return
    summary = result.summary or {}
    by_risk = summary.get("by_risk", {})
    with ui.row().classes("gap-2 mt-4 justify-center"):
        _stat_badge("匹配", summary.get("match_count", 0), "#3b82f6")
        _stat_badge("高风险", by_risk.get("high", 0), "#ef4444")
        _stat_badge("中风险", by_risk.get("medium", 0), "#f59e0b")
        _stat_badge("低风险", by_risk.get("low", 0), "#22c55e")
        _stat_badge("低置信度", summary.get("uncertain", 0), "#dc2626")


def _stat_badge(label, count, color):
    with ui.element("div").classes("px-3 py-1 rounded text-xs font-bold").style(f"background: {color}22; color: {color}; border: 1px solid {color}44;"):
        ui.label(f"{label}: {count}")


@ui.refreshable
def recent_reports():
    reports = _list_recent_reports(8)
    if not reports:
        with ui.row().classes("w-full justify-center py-6"):
            ui.label("暂无报告，拖入两个 prefab 开始对比").classes("text-gray-600 text-sm")
        return
    for path in reports:
        name = os.path.basename(path)
        mtime = time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(path)))
        with ui.row().classes("w-full items-center justify-between py-2 px-3 rounded").style("background: #0b1120; border: 1px solid #1e293b;"):
            with ui.column().classes("gap-0"):
                ui.label(name).classes("text-gray-300 text-xs font-medium")
                ui.label(mtime).classes("text-gray-600 text-xs")
            with ui.row().classes("gap-1"):
                ui.button("👁", on_click=lambda p=path: webbrowser.open(f"file://{os.path.abspath(p)}")).props("flat dense round size=sm").classes("text-blue-400 hover:text-blue-300")
                ui.button("📂", on_click=lambda p=path: os.startfile(os.path.dirname(p))).props("flat dense round size=sm").classes("text-gray-500 hover:text-gray-300")


# ── 核心逻辑 ──
def check_ready():
    ready = bool(state.before_file and state.after_file and not state.is_generating)
    if gen_btn:
        gen_btn.set_enabled(ready)
        gen_btn.set_text("🔍 生成对比报告" if ready else "请先拖入两个 prefab")
        gen_btn.style(f"background: {'#1e40af' if ready else '#334155'}; color: {'#fff' if ready else '#94a3b8'};")


def do_generate():
    if not state.before_file or not state.after_file:
        ui.notify("请先拖入两个 prefab 文件", type="warning")
        return
    state.is_generating = True
    check_ready()
    if view_btn:
        view_btn.set_visibility(False)
    if status_label:
        status_label.set_text("⏳ 正在生成...")

    try:
        result = diff_prefabs(state.before_file, state.after_file)
        paths = _default_report_paths(state.before_name, state.after_name)
        write_tree_report(result, paths["html"])
        write_json_report(result, paths["json"])
        state.last_report_html = paths["html"]
        state.last_report_json = paths["json"]

        stats_summary.refresh(result)
        recent_reports.refresh()

        ui.notify("✅ 报告生成完成", type="positive")
        if view_btn:
            view_btn.set_visibility(True)
        if status_label:
            status_label.set_text(f"✅ 已完成: {os.path.basename(paths['html'])}")
    except Exception as e:
        ui.notify(f"❌ 生成失败: {e}", type="negative")
        if status_label:
            status_label.set_text("❌ 生成失败")
    finally:
        state.is_generating = False
        check_ready()


def do_view():
    if state.last_report_html and os.path.exists(state.last_report_html):
        webbrowser.open(f"file://{os.path.abspath(state.last_report_html)}")
    else:
        ui.notify("报告文件不存在", type="warning")


# ── 布局 ──
ui.dark_mode()

with ui.column().classes("w-full min-h-screen p-4").style("background: #0b1120;"):

    # ── 顶部标题栏 ──
    with ui.row().classes("w-full items-center justify-between mb-6").style("border-bottom: 1px solid #1e293b; padding-bottom: 12px;"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("forest", size="28px").classes("text-green-400")
            ui.label("PfbDiff 树形对比工具").classes("text-h6 text-white font-bold")
        ui.button("📖 置信度说明", on_click=lambda: ui.notify("在树形报告页面右上角点击 📖 按钮查看", type="info")).props("flat dense").classes("text-gray-400 hover:text-white")

    # ── 左右拖放区 ──
    with ui.row().classes("w-full justify-center gap-4 mb-4"):
        with ui.element("div").classes("flex-1").style("max-width: 420px;"):
            before_zone()
        with ui.element("div").classes("flex-1").style("max-width: 420px;"):
            after_zone()

    # ── 操作区 ──
    with ui.row().classes("w-full justify-center gap-3 mb-2"):
        gen_btn = ui.button("请先拖入两个 prefab", on_click=do_generate).props("unelevated").classes("px-8 py-2 text-sm font-bold rounded-lg")
        gen_btn.style("background: #334155; color: #94a3b8;")
        gen_btn.set_enabled(False)

        view_btn = ui.button("👁 查看树形报告", on_click=do_view).props("unelevated").classes("px-6 py-2 text-sm font-bold rounded-lg")
        view_btn.style("background: #1e40af; color: #fff;")
        view_btn.set_visibility(False)

    # ── 统计摘要占位 ──
    stats_summary(None)

    # ── 最近报告列表 ──
    with ui.card().classes("w-full mt-6 flex-grow").style("background: #111827; border: 1px solid #1e293b;"):
        with ui.row().classes("items-center gap-2 mb-3"):
            ui.icon("folder_open", size="18px").classes("text-gray-500")
            ui.label("最近生成的报告").classes("text-gray-400 text-sm font-bold")
        recent_reports()

    # ── 底部状态栏 ──
    with ui.row().classes("w-full items-center justify-between mt-4 pt-2").style("border-top: 1px solid #1e293b;"):
        status_label = ui.label("就绪").classes("text-gray-600 text-xs")
        ui.label("v1.0.0  ·  CLI: python pfb_diff.py diff --before old.prefab --after new.prefab").classes("text-gray-700 text-xs")


# ── 启动 ──
if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        native=True,
        title="PfbDiff",
        window_size=(1100, 820),
        favicon="🌲",
    )
