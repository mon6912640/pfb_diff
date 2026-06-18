#!/usr/bin/env python3
"""PfbDiff Tkinter Desktop App — 原生拖放，能获取完整文件路径

页签一：两方对比（before / after 任意两个 prefab）
页签二：SVN 冲突分析（拖入 .working 文件或整个目录，自动定位 base/ours/theirs）
"""

import os
import re
import sys
import threading
import time
import webbrowser

def _get_project_root():
    if hasattr(sys, '_MEIPASS'):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

_PROJECT_ROOT = _get_project_root()
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
except ImportError:
    print("缺少 tkinterdnd2，请执行: pip install tkinterdnd2")
    sys.exit(1)

from diff_engine import diff_prefabs
from report_html_tree import write_html_report as write_tree_report
from report_json import write_json_report
from prefab_parser import parse_prefab
from svn_conflict_helper import find_conflict_groups, find_group_by_working, analyze_conflict, generate_reports

# ── 框架层常量/工具（见 gui_shell.py）──
from gui_shell import (
    REPORTS_DIR, COMPARE_REPORTS_DIR, CONFLICT_REPORTS_DIR,
    AppShell, ensure_dir, default_report_paths, strip_path,
    resource_path, clamp_scrollregion,
)

# ── 配色（见 gui_theme.py）──
from gui_theme import (
    BG, CARD_BG, BORDER, TEXT, TEXT_DIM, TEXT_DARK, ACCENT, RED, GREEN, YELLOW,
    PRIMARY_BTN_BG, TAB_SELECTED_BG,
)

# 框架层单例，build_app() 中创建；各回调通过它读写共享状态
shell: AppShell = None


# 「📊 两方对比」页签：实现见 gui_compare_tab.py，实例在 build_app() 创建
from gui_compare_tab import CompareTab

compare_tab: CompareTab = None

# 冲突分析页签状态
conflict_rows: list = []   # [{group, name, status, error, overview, summary, auto_open, widgets...}]
conflict_busy = False


# ═══════════════════════════════════════
# 页签二：SVN 冲突分析
# ═══════════════════════════════════════

def on_drop_conflict(event):
    path = strip_path(event.data)
    if os.path.isdir(path):
        load_conflict_dir(path)
    elif path.endswith(".working"):
        load_conflict_working(path)
    else:
        messagebox.showwarning(
            "格式错误",
            "请拖入 .prefab.working 冲突文件，或包含冲突文件的目录\n当前: " + path,
        )


def browse_conflict_file():
    path = filedialog.askopenfilename(filetypes=[("SVN 冲突文件", "*.working"), ("所有文件", "*.*")])
    if path:
        load_conflict_working(path)


def browse_conflict_dir():
    path = filedialog.askdirectory()
    if path:
        load_conflict_dir(path)


def load_conflict_working(path: str):
    """单个 .working 文件：自动定位同组文件，立即分析并打开概览"""
    if conflict_busy:
        messagebox.showinfo("提示", "正在分析中，请稍候")
        return
    try:
        group = find_group_by_working(path)
    except ValueError as e:
        messagebox.showerror("无法定位冲突组", str(e))
        return
    _populate_conflict_rows([{"group": group, "name": group["name"], "status": "ready"}])
    conflict_hint_lbl.config(text=f"已定位冲突组（来自 {os.path.basename(path)}）")
    _start_conflict_jobs([0], auto_open=True)


def load_conflict_dir(path: str):
    """目录：扫描所有冲突组，等用户确认后分析"""
    if conflict_busy:
        messagebox.showinfo("提示", "正在分析中，请稍候")
        return
    try:
        groups = find_conflict_groups(path)
    except OSError as e:
        messagebox.showerror("扫描失败", str(e))
        return

    # 不完整的冲突组（有 .working 但缺 merge-left / merge-right）也列出来提示
    found_names = {g["name"] for g in groups}
    orphans = []
    for f in os.listdir(path):
        if f.endswith(".working") and ".prefab." in f:
            prefix = f[: -len(".working")]
            if prefix not in found_names:
                orphans.append(prefix)

    rows = [{"group": g, "name": g["name"], "status": "ready"} for g in groups]
    rows += [{"group": None, "name": n, "status": "missing"} for n in sorted(orphans)]

    if not rows:
        conflict_hint_lbl.config(text=f"未在 {path} 发现 SVN 冲突文件组")
        _populate_conflict_rows([])
        return

    _populate_conflict_rows(rows)
    conflict_hint_lbl.config(
        text=f"在 {os.path.basename(path) or path} 发现 {len(groups)} 个冲突组"
             + (f"，{len(orphans)} 个缺少文件" if orphans else "")
    )


def _populate_conflict_rows(rows: list):
    """重建冲突组列表 UI"""
    global conflict_rows
    conflict_rows = rows
    for w in conflict_list_frame.winfo_children():
        w.destroy()

    if not rows:
        tk.Label(conflict_list_frame, text="拖入冲突文件或目录后，这里会列出冲突组",
                 bg=CARD_BG, fg=TEXT_DARK, font=("Microsoft YaHei", 9)).pack(pady=16)
        analyze_all_btn.config(state="disabled")
        _update_scroll_region()  # 清空后必须重设滚动区域，否则残留上一次的可滚动高度
        return

    for i, row in enumerate(rows):
        frame = tk.Frame(conflict_list_frame, bg=CARD_BG)
        frame.pack(fill="x", padx=4, pady=2)

        tk.Label(frame, text=row["name"], bg=CARD_BG, fg=TEXT,
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left")

        status_lbl_w = tk.Label(frame, text="", bg=CARD_BG, fg=TEXT_DIM, font=("Microsoft YaHei", 9))
        status_lbl_w.pack(side="left", padx=8)

        summary_lbl_w = tk.Label(frame, text="", bg=CARD_BG, fg=TEXT_DIM, font=("Microsoft YaHei", 9))
        summary_lbl_w.pack(side="left", padx=4)

        view_btn_w = tk.Button(frame, text="👁 查看概览", bg=CARD_BG, fg=ACCENT, bd=0,
                               cursor="hand2", state="disabled", font=("Microsoft YaHei", 9))
        view_btn_w.pack(side="right", padx=4)

        analyze_btn_w = tk.Button(frame, text="🔍 分析", bg=CARD_BG, fg=ACCENT, bd=0,
                                  cursor="hand2", font=("Microsoft YaHei", 9),
                                  command=lambda i=i: _start_conflict_jobs([i]))
        analyze_btn_w.pack(side="right", padx=4)

        row["w_status"] = status_lbl_w
        row["w_summary"] = summary_lbl_w
        row["w_view"] = view_btn_w
        row["w_analyze"] = analyze_btn_w
        _render_row_status(i)

    has_ready = any(r["status"] == "ready" for r in rows)
    analyze_all_btn.config(state="normal" if has_ready else "disabled")
    _update_analyze_all_text()
    _update_scroll_region()


def _render_row_status(i: int):
    row = conflict_rows[i]
    texts = {
        "ready": ("待分析", TEXT_DARK),
        "queued": ("排队中", TEXT_DIM),
        "running": ("⏳ 分析中...", YELLOW),
        "done": ("✓ 完成", GREEN),
        "error": ("❌ 失败", RED),
        "missing": ("⚠ 缺少 merge-left / merge-right 文件", YELLOW),
    }
    text, color = texts.get(row["status"], ("", TEXT_DIM))
    row["w_status"].config(text=text, fg=color)

    # 按钮文案跟随状态：未分析→分析，已完成→重新分析，失败→重试
    btn_texts = {"done": "🔄 重新分析", "error": "🔄 重试"}
    row["w_analyze"].config(text=btn_texts.get(row["status"], "🔍 分析"))

    if row["status"] == "missing":
        row["w_analyze"].config(state="disabled")
    if row["status"] == "done":
        s = row["summary"]
        hard = s["both_modified_nodes"] + s["tree_conflicts"]
        if hard:
            summary = f"真冲突 {s['both_modified_nodes']} · 树级 {s['tree_conflicts']} · 一致 {s['convergent_nodes']}"
            color = RED
        else:
            summary = (f"无真冲突 · 一致 {s['convergent_nodes']} · "
                       f"仅ours {s['only_ours_nodes']} · 仅theirs {s['only_theirs_nodes']}")
            color = GREEN
        row["w_summary"].config(text=summary, fg=color)
        row["w_view"].config(state="normal", command=lambda p=row["overview"]: shell.open_report(p))
    elif row["status"] == "error":
        row["w_summary"].config(text=row.get("error", ""), fg=RED)


def _update_analyze_all_text():
    """全部分析按钮文案：列表里还有没分析过的→全部分析；全都跑过了→重新全部分析"""
    actionable = [r for r in conflict_rows if r["status"] != "missing"]
    if actionable and all(r["status"] in ("done", "error") for r in actionable):
        analyze_all_btn.config(text="🔄 重新全部分析")
    else:
        analyze_all_btn.config(text="🔍 全部分析")


def _set_conflict_controls(enabled: bool):
    state_str = "normal" if enabled else "disabled"
    analyze_all_btn.config(state=state_str if any(r["status"] != "missing" for r in conflict_rows) else "disabled")
    for r in conflict_rows:
        if r["status"] != "missing":
            r["w_analyze"].config(state=state_str)
    _update_analyze_all_text()


def analyze_all_conflicts():
    _start_conflict_jobs([i for i, r in enumerate(conflict_rows) if r["status"] in ("ready", "error", "done")])


def _start_conflict_jobs(indices: list, auto_open: bool = False):
    global conflict_busy
    if conflict_busy or not indices:
        return
    jobs = [i for i in indices if conflict_rows[i]["status"] != "missing"]
    if not jobs:
        return
    conflict_busy = True
    _set_conflict_controls(False)
    for i in jobs:
        conflict_rows[i]["status"] = "queued"
        conflict_rows[i]["auto_open"] = auto_open
        _render_row_status(i)
    threading.Thread(target=_conflict_worker, args=(jobs,), daemon=True).start()


def _conflict_worker(jobs: list):
    """后台线程：逐组分析。所有 UI 更新通过 root.after 回主线程。"""
    ensure_dir(CONFLICT_REPORTS_DIR)
    for i in jobs:
        row = conflict_rows[i]
        root.after(0, _on_row_running, i)
        try:
            data = analyze_conflict(
                row["group"],
                progress=lambda m: root.after(0, shell.set_status, m.strip()),
            )
            overview = generate_reports(data, CONFLICT_REPORTS_DIR, progress=lambda m: None)
            root.after(0, _on_row_done, i, data["summary"], overview)
        except Exception as e:
            root.after(0, _on_row_fail, i, str(e))
    root.after(0, _on_all_jobs_done)


def _on_row_running(i: int):
    conflict_rows[i]["status"] = "running"
    _render_row_status(i)


def _on_row_done(i: int, summary: dict, overview: str):
    row = conflict_rows[i]
    row["status"] = "done"
    row["summary"] = summary
    row["overview"] = overview
    _render_row_status(i)
    if row.get("auto_open"):
        shell.open_report(overview)


def _on_row_fail(i: int, error: str):
    conflict_rows[i]["status"] = "error"
    conflict_rows[i]["error"] = error
    _render_row_status(i)


def _on_all_jobs_done():
    global conflict_busy
    conflict_busy = False
    _set_conflict_controls(True)
    done = sum(1 for r in conflict_rows if r["status"] == "done")
    failed = sum(1 for r in conflict_rows if r["status"] == "error")
    shell.set_status(f"✅ 冲突分析完成 {done} 组" + (f"，失败 {failed} 组" if failed else ""))
    shell.load_recent_reports()


# ═══════════════════════════════════════
# 界面构建
# ═══════════════════════════════════════

def _build_conflict_tab(parent):
    global conflict_hint_lbl, conflict_list_frame, analyze_all_btn, conflict_canvas

    # ── 拖放区 ──
    drop_card = tk.Frame(parent, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=2)
    drop_card.pack(fill="x", padx=16, pady=(16, 8))
    drop_card.drop_target_register(DND_FILES)
    drop_card.dnd_bind("<<Drop>>", on_drop_conflict)

    tk.Label(drop_card, text="🌲 拖入 .prefab.working 冲突文件（自动定位同组并分析）",
             bg=CARD_BG, fg=TEXT_DIM, font=("Microsoft YaHei", 11)).pack(pady=(14, 0))
    tk.Label(drop_card, text="或拖入整个目录，自动扫描所有 SVN 冲突组",
             bg=CARD_BG, fg=TEXT_DARK, font=("Microsoft YaHei", 9)).pack()
    btn_bar = tk.Frame(drop_card, bg=CARD_BG)
    btn_bar.pack(pady=(4, 12))
    tk.Button(btn_bar, text="📂 选择 .working 文件", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2",
              command=browse_conflict_file, font=("Microsoft YaHei", 9)).pack(side="left", padx=8)
    tk.Button(btn_bar, text="📁 选择目录扫描", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2",
              command=browse_conflict_dir, font=("Microsoft YaHei", 9)).pack(side="left", padx=8)

    # ── 列表头 ──
    head_bar = tk.Frame(parent, bg=BG)
    head_bar.pack(fill="x", padx=16, pady=(8, 0))
    conflict_hint_lbl = tk.Label(head_bar, text="尚未加载冲突文件", bg=BG, fg=TEXT_DIM, font=("Microsoft YaHei", 9))
    conflict_hint_lbl.pack(side="left")
    analyze_all_btn = tk.Button(head_bar, text="🔍 全部分析", bg=PRIMARY_BTN_BG, fg=TEXT, bd=0, padx=14, pady=4,
                                cursor="hand2", state="disabled", command=analyze_all_conflicts,
                                font=("Microsoft YaHei", 9, "bold"))
    analyze_all_btn.pack(side="right")

    # ── 冲突组列表（可滚动）──
    list_container = tk.Frame(parent, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
    list_container.pack(fill="both", expand=True, padx=16, pady=8)

    conflict_canvas = tk.Canvas(list_container, bg=CARD_BG, highlightthickness=0)
    scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=conflict_canvas.yview)
    conflict_list_frame = tk.Frame(conflict_canvas, bg=CARD_BG)

    conflict_list_frame.bind("<Configure>", lambda e: _update_scroll_region())
    canvas_window = conflict_canvas.create_window((0, 0), window=conflict_list_frame, anchor="nw")
    conflict_canvas.bind("<Configure>", lambda e: (conflict_canvas.itemconfig(canvas_window, width=e.width),
                                                   _update_scroll_region()))
    conflict_canvas.configure(yscrollcommand=scrollbar.set)

    conflict_canvas.pack(side="left", fill="both", expand=True, padx=4, pady=4)
    scrollbar.pack(side="right", fill="y")

    shell.register_scroll(conflict_canvas)

    _populate_conflict_rows([])


def _update_scroll_region():
    # 等布局完成后再取 bbox，避免拿到重建前的旧尺寸
    conflict_canvas.after_idle(lambda: clamp_scrollregion(conflict_canvas))


# ═══════════════════════════════════════
# 主窗口
# ═══════════════════════════════════════

def build_app():
    """构建主窗口及全部子控件，但不进入事件循环。

    返回根窗口。拆出此函数是为了让无头测试能构建完整 UI 并驱动回调，
    而不阻塞在 mainloop 上；run_gui 只是它加一句 mainloop 的薄封装。
    """
    global root, shell, notebook, compare_tab

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
    notebook.add(tab_compare, text="  📊 两方对比  ")
    notebook.add(tab_conflict, text="  🌲 SVN 冲突分析  ")

    compare_tab = CompareTab(shell, tab_compare)
    _build_conflict_tab(tab_conflict)
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
