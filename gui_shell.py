#!/usr/bin/env python3
"""PfbDiff GUI 框架层。

从 gui.py 抽出：报告目录常量、无状态路径工具，以及 AppShell ——
统管主窗口共享部分（状态栏、最近报告列表、页签切换、鼠标滚轮）。
各页签持有同一个 AppShell 实例，通过它读写共享状态，不再依赖模块级全局。
"""

import os
import re
import sys
import time
import webbrowser

import tkinter as tk
from tkinter import ttk

from gui_theme import (
    BG, CARD_BG, BORDER, TEXT, TEXT_DIM, TEXT_DARK, ACCENT, FONT_FAMILY,
)


def _get_project_root() -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


_PROJECT_ROOT = _get_project_root()

# reports/ 按功能分子目录：每新增一个页签功能就新增一个子目录
REPORTS_DIR = os.path.join(_PROJECT_ROOT, "reports")
COMPARE_REPORTS_DIR = os.path.join(REPORTS_DIR, "compare")        # 两方对比报告
CONFLICT_REPORTS_DIR = os.path.join(REPORTS_DIR, "svn_conflict")  # 冲突分析报告
REVISION_REPORTS_DIR = os.path.join(REPORTS_DIR, "revision")      # 同分支版本对比报告
BRANCH_REPORTS_DIR = os.path.join(REPORTS_DIR, "branch")          # 跨分支对比报告

# 冲突分析的子报告（ours/theirs/交叉对比），最近报告列表里隐藏，从概览页内链接进入
_SUB_REPORT_RE = re.compile(r"_(ours|theirs|ours_vs_theirs)_\d{8}_\d{6}\.html$")


# ── 无状态工具 ──
def ensure_dir(path: str) -> None:
    if not os.path.isdir(path):
        os.makedirs(path)


def safe_name(name: str) -> str:
    base = os.path.basename(name)
    if base.endswith(".prefab"):
        base = base[:-7]
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in base) or "prefab"


def default_report_paths(before_name: str, after_name: str) -> dict:
    ensure_dir(COMPARE_REPORTS_DIR)
    bn = safe_name(before_name)
    an = safe_name(after_name)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = f"{bn}__to__{an}_{stamp}" if bn != an else f"{bn}_diff_{stamp}"
    return {
        "html": os.path.join(COMPARE_REPORTS_DIR, base + ".html"),
        "json": os.path.join(COMPARE_REPORTS_DIR, base + ".json"),
    }


def strip_path(raw: str) -> str:
    """tkinterdnd2 Windows 路径可能有 {} 包裹，去掉它"""
    raw = raw.strip()
    if raw.startswith("{") and raw.endswith("}"):
        raw = raw[1:-1]
    return raw


def resource_path(rel: str) -> str:
    """兼容 PyInstaller 打包后的资源路径"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel)
    return os.path.join(_PROJECT_ROOT, rel)


def clamp_scrollregion(canvas: tk.Canvas) -> None:
    """滚动区域夹紧到内容大小；内容不足一屏时撑满视口高度，使列表不可滚动"""
    bbox = canvas.bbox("all")
    content_w = bbox[2] if bbox else 0
    content_h = bbox[3] if bbox else 0
    view_h = max(canvas.winfo_height(), 1)
    canvas.configure(scrollregion=(0, 0, content_w, max(content_h, view_h)))
    if content_h <= view_h:
        canvas.yview_moveto(0)


class AppShell:
    """主窗口共享框架：状态栏、最近报告列表、页签切换、鼠标滚轮。"""

    def __init__(self, root: tk.Misc):
        self.root = root
        self.scroll_canvases: list = []          # 支持鼠标滚轮的 Canvas（冲突列表、最近报告）
        self.current_reports_dir = COMPARE_REPORTS_DIR  # 最近报告列表当前展示目录（随页签切换）
        self.status_lbl = None
        self.recent_frame = None
        self.recent_title_lbl = None
        self.recent_canvas = None

    # ── 状态栏 ──
    def build_status_bar(self, parent: tk.Misc) -> None:
        self.status_lbl = tk.Label(parent, text="就绪", bg=BG, fg=TEXT_DARK, font=(FONT_FAMILY, 9))
        self.status_lbl.pack(anchor="w", padx=16, pady=(0, 4))

    def set_status(self, text: str) -> None:
        if self.status_lbl is not None:
            self.status_lbl.config(text=text)

    # ── 报告打开 ──
    def open_report(self, path: str) -> None:
        webbrowser.open(f"file://{os.path.abspath(path)}")

    # ── 滚轮 ──
    def register_scroll(self, canvas: tk.Canvas) -> None:
        self.scroll_canvases.append(canvas)

    def on_mousewheel(self, event) -> None:
        # 滚动鼠标所在的那个列表；内容不足一屏时不滚动
        w = self.root.winfo_containing(event.x_root, event.y_root)
        while w is not None:
            if w in self.scroll_canvases:
                if w.yview() != (0.0, 1.0):
                    w.yview_scroll(int(-event.delta / 120), "units")
                return
            w = w.master

    # ── 最近报告列表 ──
    def build_recent_panel(self, parent: tk.Misc) -> None:
        recent_container = tk.Frame(parent, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        recent_container.pack(fill="x", padx=16, pady=(0, 12))
        self.recent_title_lbl = tk.Label(recent_container, text="📁 最近生成的报告（两方对比）",
                                         bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 10, "bold"))
        self.recent_title_lbl.pack(anchor="w", padx=8, pady=8)

        recent_body = tk.Frame(recent_container, bg=CARD_BG)
        recent_body.pack(fill="x", padx=4, pady=(0, 8))
        self.recent_canvas = tk.Canvas(recent_body, bg=CARD_BG, highlightthickness=0, height=150)
        recent_scrollbar = ttk.Scrollbar(recent_body, orient="vertical", command=self.recent_canvas.yview)
        self.recent_frame = tk.Frame(self.recent_canvas, bg=CARD_BG)

        self.recent_frame.bind(
            "<Configure>",
            lambda e: self.recent_canvas.after_idle(lambda: clamp_scrollregion(self.recent_canvas)),
        )
        recent_window = self.recent_canvas.create_window((0, 0), window=self.recent_frame, anchor="nw")
        self.recent_canvas.bind(
            "<Configure>",
            lambda e: (self.recent_canvas.itemconfig(recent_window, width=e.width),
                       self.recent_canvas.after_idle(lambda: clamp_scrollregion(self.recent_canvas))),
        )
        self.recent_canvas.configure(yscrollcommand=recent_scrollbar.set)

        self.recent_canvas.pack(side="left", fill="x", expand=True, padx=4)
        recent_scrollbar.pack(side="right", fill="y")
        self.register_scroll(self.recent_canvas)

    def load_recent_reports(self) -> None:
        for widget in self.recent_frame.winfo_children():
            widget.destroy()

        ensure_dir(self.current_reports_dir)
        is_compare_dir = self.current_reports_dir == COMPARE_REPORTS_DIR
        files = []
        for f in os.listdir(self.current_reports_dir):
            if not f.endswith(".html"):
                continue
            if _SUB_REPORT_RE.search(f):
                continue  # 冲突分析的子报告从概览页进入，列表里不重复展示
            if is_compare_dir and "_conflict_overview_" in f:
                continue  # 历史遗留在根目录的冲突概览不混入两方对比列表
            p = os.path.join(self.current_reports_dir, f)
            if not os.path.isfile(p):
                continue
            files.append((p, os.path.getmtime(p)))
        files.sort(key=lambda x: x[1], reverse=True)

        if not files:
            tk.Label(self.recent_frame, text="暂无报告", bg=CARD_BG, fg=TEXT_DARK,
                     font=(FONT_FAMILY, 10)).pack(pady=10)
            return

        for path, mtime in files[:50]:
            name = os.path.basename(path)
            t = time.strftime("%m-%d %H:%M", time.localtime(mtime))
            tag = "🌲" if "_conflict_overview_" in name else "📊"
            row = tk.Frame(self.recent_frame, bg=CARD_BG)
            row.pack(fill="x", padx=4, pady=2)
            tk.Label(row, text=f"{tag} {name}", bg=CARD_BG, fg=TEXT, font=(FONT_FAMILY, 9, "bold")).pack(side="left")
            tk.Label(row, text=t, bg=CARD_BG, fg=TEXT_DARK, font=(FONT_FAMILY, 9)).pack(side="left", padx=8)
            tk.Button(row, text="👁", bg=CARD_BG, fg=ACCENT, bd=0,
                      command=lambda p=path: self.open_report(p)).pack(side="right")
            tk.Button(row, text="📂", bg=CARD_BG, fg=TEXT_DIM, bd=0,
                      command=lambda p=path: os.startfile(os.path.dirname(p))).pack(side="right", padx=4)

        self.recent_canvas.yview_moveto(0)  # 重载后回到列表顶部

    # 页签 index → (报告目录, 列表标题)。新增页签时在此登记一行即可。
    TAB_REPORTS = [
        (COMPARE_REPORTS_DIR, "📁 最近生成的报告（两方对比）"),
        (CONFLICT_REPORTS_DIR, "📁 最近生成的报告（冲突分析）"),
        (REVISION_REPORTS_DIR, "📁 最近生成的报告（版本对比）"),
        (BRANCH_REPORTS_DIR, "📁 最近生成的报告（分支对比）"),
    ]

    # ── 页签切换 ──
    def on_tab_changed(self, event) -> None:
        """切换页签时，最近报告列表切换到对应目录"""
        idx = event.widget.index(event.widget.select())
        directory, title = self.TAB_REPORTS[idx] if idx < len(self.TAB_REPORTS) else self.TAB_REPORTS[0]
        self.current_reports_dir = directory
        self.recent_title_lbl.config(text=title)
        self.load_recent_reports()
