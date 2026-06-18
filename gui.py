#!/usr/bin/env python3
"""PfbDiff Tkinter Desktop App — 原生拖放，能获取完整文件路径

页签一：两方对比（before / after 任意两个 prefab）
页签二：SVN 冲突分析（拖入 .working 文件或整个目录，自动定位 base/ours/theirs）
"""

import os
import sys


def _get_project_root():
    if hasattr(sys, '_MEIPASS'):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


_PROJECT_ROOT = _get_project_root()
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import tkinter as tk
from tkinter import ttk

try:
    from tkinterdnd2 import TkinterDnD
except ImportError:
    print("缺少 tkinterdnd2，请执行: pip install tkinterdnd2")
    sys.exit(1)

from gui_shell import AppShell, resource_path
from gui_theme import BG, CARD_BG, BORDER, TEXT, TEXT_DIM, TAB_SELECTED_BG
from gui_compare_tab import CompareTab
from gui_conflict_tab import ConflictTab
from gui_revision_tab import RevisionTab

# 框架与各页签实例，均在 build_app() 中创建
shell: AppShell = None
compare_tab: CompareTab = None
conflict_tab: ConflictTab = None
revision_tab: RevisionTab = None


# ═══════════════════════════════════════
# 主窗口
# ═══════════════════════════════════════

def build_app():
    """构建主窗口及全部子控件，但不进入事件循环。

    返回根窗口。拆出此函数是为了让无头测试能构建完整 UI 并驱动回调，
    而不阻塞在 mainloop 上；run_gui 只是它加一句 mainloop 的薄封装。
    """
    global root, shell, notebook, compare_tab, conflict_tab, revision_tab

    root = TkinterDnD.Tk()
    shell = AppShell(root)
    root.title("PfbDiff 预制体对比工具")
    root.geometry("920x760")
    root.configure(bg=BG)

    _icon_path = resource_path("icon.ico")
    if os.path.isfile(_icon_path):
        try:
            root.iconbitmap(_icon_path)
        except Exception:
            pass

    # 标题栏
    title_bar = tk.Frame(root, bg=BG)
    title_bar.pack(fill="x", padx=16, pady=12)
    tk.Label(title_bar, text="🌲 PfbDiff 预制体对比工具", bg=BG, fg=TEXT, font=("Microsoft YaHei", 14, "bold")).pack(side="left")

    # 页签（深色样式）
    style = ttk.Style(root)
    style.theme_use("default")
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", background=CARD_BG, foreground=TEXT_DIM,
                    padding=[16, 7], font=("Microsoft YaHei", 10))
    style.map("TNotebook.Tab",
              background=[("selected", TAB_SELECTED_BG)],
              foreground=[("selected", TEXT)])
    style.configure("Vertical.TScrollbar", background=BORDER, troughcolor=CARD_BG, borderwidth=0)

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=16, pady=(0, 4))

    tab_compare = tk.Frame(notebook, bg=BG)
    tab_conflict = tk.Frame(notebook, bg=BG)
    tab_revision = tk.Frame(notebook, bg=BG)
    notebook.add(tab_compare, text="  📊 两方对比  ")
    notebook.add(tab_conflict, text="  🌲 SVN 冲突分析  ")
    notebook.add(tab_revision, text="  📜 版本对比  ")

    compare_tab = CompareTab(shell, tab_compare)
    conflict_tab = ConflictTab(shell, tab_conflict)
    revision_tab = RevisionTab(shell, tab_revision)
    notebook.bind("<<NotebookTabChanged>>", shell.on_tab_changed)

    # 状态栏 + 最近报告列表（两个页签共用），均由 AppShell 持有
    shell.build_status_bar(root)
    shell.build_recent_panel(root)

    root.bind_all("<MouseWheel>", shell.on_mousewheel)
    shell.load_recent_reports()

    return root


def run_gui():
    build_app()
    root.mainloop()


if __name__ == "__main__":
    run_gui()
