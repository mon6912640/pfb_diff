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

# ── 常量 ──
# reports/ 按功能分子目录：每新增一个页签功能就新增一个子目录
REPORTS_DIR = os.path.join(_PROJECT_ROOT, "reports")
COMPARE_REPORTS_DIR = os.path.join(REPORTS_DIR, "compare")        # 两方对比报告
CONFLICT_REPORTS_DIR = os.path.join(REPORTS_DIR, "svn_conflict")  # 冲突分析报告

# 冲突分析的子报告（ours/theirs/交叉对比），最近报告列表里隐藏，从概览页内链接进入
_SUB_REPORT_RE = re.compile(r"_(ours|theirs|ours_vs_theirs)_\d{8}_\d{6}\.html$")

# ── 配色 ──
BG = "#0b1120"
CARD_BG = "#111827"
BORDER = "#334155"
TEXT = "#e2e8f0"
TEXT_DIM = "#94a3b8"
TEXT_DARK = "#64748b"
ACCENT = "#3b82f6"
RED = "#ef4444"
GREEN = "#22c55e"
YELLOW = "#f59e0b"


class AppState:
    def __init__(self):
        self.before_file: str | None = None
        self.after_file: str | None = None
        self.before_name: str = ""
        self.after_name: str = ""
        self.before_path: str = ""
        self.after_path: str = ""


state = AppState()

# 冲突分析页签状态
conflict_rows: list = []   # [{group, name, status, error, overview, summary, auto_open, widgets...}]
conflict_busy = False

# 最近报告列表当前展示的目录（随页签切换）
current_reports_dir = COMPARE_REPORTS_DIR


# ── 工具 ──
def _ensure_dir(path: str) -> None:
    if not os.path.isdir(path):
        os.makedirs(path)


def _safe_name(name: str) -> str:
    base = os.path.basename(name)
    if base.endswith(".prefab"):
        base = base[:-7]
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in base) or "prefab"


def _default_report_paths(before_name: str, after_name: str):
    _ensure_dir(COMPARE_REPORTS_DIR)
    bn = _safe_name(before_name)
    an = _safe_name(after_name)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = f"{bn}__to__{an}_{stamp}" if bn != an else f"{bn}_diff_{stamp}"
    return {
        "html": os.path.join(COMPARE_REPORTS_DIR, base + ".html"),
        "json": os.path.join(COMPARE_REPORTS_DIR, base + ".json"),
    }


def _parse_info(file_path: str):
    try:
        doc = parse_prefab(file_path)
        return {"ok": True, "node_count": len(doc.nodes)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _strip_path(raw: str) -> str:
    """tkinterdnd2 Windows 路径可能有 {} 包裹，去掉它"""
    raw = raw.strip()
    if raw.startswith("{") and raw.endswith("}"):
        raw = raw[1:-1]
    return raw


def _open_report(path: str) -> None:
    webbrowser.open(f"file://{os.path.abspath(path)}")


# ═══════════════════════════════════════
# 页签一：两方对比
# ═══════════════════════════════════════

def on_drop_before(event):
    path = _strip_path(event.data)
    if not path.lower().endswith(".prefab"):
        messagebox.showwarning("格式错误", f"请选择 .prefab 文件\n当前: {path}")
        return
    state.before_file = path
    state.before_name = os.path.basename(path)
    state.before_path = path
    update_before_ui()


def on_drop_after(event):
    path = _strip_path(event.data)
    if not path.lower().endswith(".prefab"):
        messagebox.showwarning("格式错误", f"请选择 .prefab 文件\n当前: {path}")
        return
    state.after_file = path
    state.after_name = os.path.basename(path)
    state.after_path = path
    update_after_ui()


def browse_before():
    path = filedialog.askopenfilename(filetypes=[("Prefab files", "*.prefab")])
    if not path:
        return
    state.before_file = path
    state.before_name = os.path.basename(path)
    state.before_path = path
    update_before_ui()


def browse_after():
    path = filedialog.askopenfilename(filetypes=[("Prefab files", "*.prefab")])
    if not path:
        return
    state.after_file = path
    state.after_name = os.path.basename(path)
    state.after_path = path
    update_after_ui()


def remove_before():
    state.before_file = None
    state.before_name = ""
    state.before_path = ""
    update_before_ui()


def remove_after():
    state.after_file = None
    state.after_name = ""
    state.after_path = ""
    update_after_ui()


def update_before_ui():
    if state.before_file:
        info = _parse_info(state.before_file)
        before_name_lbl.config(text=state.before_name)
        if info["ok"]:
            before_meta_lbl.config(text=f"📄 {info['node_count']} 节点")
        else:
            before_meta_lbl.config(text=f"⚠️ {info['error']}")
        before_path_lbl.config(text=state.before_path)
        before_drop_frame.pack_forget()
        before_info_frame.pack(fill="both", expand=True, padx=8, pady=8)
    else:
        before_name_lbl.config(text="")
        before_meta_lbl.config(text="")
        before_path_lbl.config(text="")
        before_info_frame.pack_forget()
        before_drop_frame.pack(fill="both", expand=True, padx=8, pady=8)
    check_ready()


def update_after_ui():
    if state.after_file:
        info = _parse_info(state.after_file)
        after_name_lbl.config(text=state.after_name)
        if info["ok"]:
            after_meta_lbl.config(text=f"📄 {info['node_count']} 节点")
        else:
            after_meta_lbl.config(text=f"⚠️ {info['error']}")
        after_path_lbl.config(text=state.after_path)
        after_drop_frame.pack_forget()
        after_info_frame.pack(fill="both", expand=True, padx=8, pady=8)
    else:
        after_name_lbl.config(text="")
        after_meta_lbl.config(text="")
        after_path_lbl.config(text="")
        after_info_frame.pack_forget()
        after_drop_frame.pack(fill="both", expand=True, padx=8, pady=8)
    check_ready()


def check_ready():
    ready = bool(state.before_file and state.after_file)
    gen_btn.config(
        state="normal" if ready else "disabled",
        text="🔍 生成对比报告" if ready else "请先拖入两个 prefab",
    )


def do_generate():
    if not state.before_file or not state.after_file:
        messagebox.showwarning("提示", "请先选择两个 prefab 文件")
        return
    gen_btn.config(state="disabled", text="⏳ 正在生成...")
    root.update()

    try:
        result = diff_prefabs(state.before_file, state.after_file)
        if state.before_path:
            result.before_path = state.before_path
        if state.after_path:
            result.after_path = state.after_path
        paths = _default_report_paths(state.before_name, state.after_name)
        write_tree_report(result, paths["html"])
        write_json_report(result, paths["json"])

        status_lbl.config(text=f"✅ 已完成: {os.path.basename(paths['html'])}")
        view_btn.config(state="normal", command=lambda: _open_report(paths["html"]))
        load_recent_reports()
        messagebox.showinfo("完成", "报告生成成功")
    except Exception as e:
        messagebox.showerror("失败", f"生成失败: {e}")
        status_lbl.config(text="❌ 生成失败")
    finally:
        check_ready()


# ═══════════════════════════════════════
# 页签二：SVN 冲突分析
# ═══════════════════════════════════════

def on_drop_conflict(event):
    path = _strip_path(event.data)
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
        row["w_view"].config(state="normal", command=lambda p=row["overview"]: _open_report(p))
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
    _ensure_dir(CONFLICT_REPORTS_DIR)
    for i in jobs:
        row = conflict_rows[i]
        root.after(0, _on_row_running, i)
        try:
            data = analyze_conflict(
                row["group"],
                progress=lambda m: root.after(0, status_lbl.config, {"text": m.strip()}),
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
        _open_report(overview)


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
    status_lbl.config(text=f"✅ 冲突分析完成 {done} 组" + (f"，失败 {failed} 组" if failed else ""))
    load_recent_reports()


# ═══════════════════════════════════════
# 最近报告
# ═══════════════════════════════════════

def load_recent_reports():
    for widget in recent_frame.winfo_children():
        widget.destroy()

    _ensure_dir(current_reports_dir)
    is_compare_dir = current_reports_dir == COMPARE_REPORTS_DIR
    files = []
    for f in os.listdir(current_reports_dir):
        if not f.endswith(".html"):
            continue
        if _SUB_REPORT_RE.search(f):
            continue  # 冲突分析的子报告从概览页进入，列表里不重复展示
        if is_compare_dir and "_conflict_overview_" in f:
            continue  # 历史遗留在根目录的冲突概览不混入两方对比列表
        p = os.path.join(current_reports_dir, f)
        if not os.path.isfile(p):
            continue
        files.append((p, os.path.getmtime(p)))
    files.sort(key=lambda x: x[1], reverse=True)

    if not files:
        tk.Label(recent_frame, text="暂无报告", bg=CARD_BG, fg=TEXT_DARK, font=("Microsoft YaHei", 10)).pack(pady=10)
        return

    for path, mtime in files[:50]:
        name = os.path.basename(path)
        t = time.strftime("%m-%d %H:%M", time.localtime(mtime))
        tag = "🌲" if "_conflict_overview_" in name else "📊"
        row = tk.Frame(recent_frame, bg=CARD_BG)
        row.pack(fill="x", padx=4, pady=2)
        tk.Label(row, text=f"{tag} {name}", bg=CARD_BG, fg=TEXT, font=("Microsoft YaHei", 9, "bold")).pack(side="left")
        tk.Label(row, text=t, bg=CARD_BG, fg=TEXT_DARK, font=("Microsoft YaHei", 9)).pack(side="left", padx=8)
        tk.Button(
            row, text="👁", bg=CARD_BG, fg=ACCENT, bd=0,
            command=lambda p=path: _open_report(p),
        ).pack(side="right")
        tk.Button(
            row, text="📂", bg=CARD_BG, fg=TEXT_DIM, bd=0,
            command=lambda p=path: os.startfile(os.path.dirname(p)),
        ).pack(side="right", padx=4)

    recent_canvas.yview_moveto(0)  # 重载后回到列表顶部


def _get_resource_path(rel: str) -> str:
    """兼容 PyInstaller 打包后的资源路径"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel)
    return os.path.join(_PROJECT_ROOT, rel)


# ═══════════════════════════════════════
# 界面构建
# ═══════════════════════════════════════

def _build_compare_tab(parent):
    global before_drop_frame, before_info_frame, before_name_lbl, before_meta_lbl, before_path_lbl
    global after_drop_frame, after_info_frame, after_name_lbl, after_meta_lbl, after_path_lbl
    global gen_btn, view_btn

    drop_area = tk.Frame(parent, bg=BG)
    drop_area.pack(fill="both", expand=True, padx=8, pady=8)
    drop_area.grid_columnconfigure(0, weight=1)
    drop_area.grid_columnconfigure(1, weight=1)
    drop_area.grid_rowconfigure(0, weight=1)

    # ── Before 卡片 ──
    before_card = tk.Frame(drop_area, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=2)
    before_card.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    before_drop_frame = tk.Frame(before_card, bg=CARD_BG)
    before_drop_frame.pack(fill="both", expand=True)
    before_drop_frame.drop_target_register(DND_FILES)
    before_drop_frame.dnd_bind("<<Drop>>", on_drop_before)

    tk.Label(before_drop_frame, text="⬅ Before（旧版本）", bg=CARD_BG, fg=TEXT_DIM, font=("Microsoft YaHei", 10, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
    tk.Label(before_drop_frame, text="拖入旧版本 .prefab", bg=CARD_BG, fg=TEXT_DIM, font=("Microsoft YaHei", 11)).pack(expand=True)
    tk.Label(before_drop_frame, text="或点击选择文件", bg=CARD_BG, fg=TEXT_DARK, font=("Microsoft YaHei", 9)).pack()
    tk.Button(before_drop_frame, text="📂 浏览...", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2", command=browse_before, font=("Microsoft YaHei", 9)).pack(pady=8)

    before_info_frame = tk.Frame(before_card, bg=CARD_BG)
    tk.Label(before_info_frame, text="⬅ Before（旧版本）", bg=CARD_BG, fg=TEXT_DIM, font=("Microsoft YaHei", 10, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
    before_name_lbl = tk.Label(before_info_frame, text="", bg=CARD_BG, fg=TEXT, font=("Microsoft YaHei", 10, "bold"))
    before_name_lbl.pack(anchor="w", padx=8, pady=(4, 0))
    before_meta_lbl = tk.Label(before_info_frame, text="", bg=CARD_BG, fg=TEXT_DIM, font=("Microsoft YaHei", 9))
    before_meta_lbl.pack(anchor="w", padx=8)
    before_path_lbl = tk.Label(before_info_frame, text="", bg=CARD_BG, fg=TEXT_DARK, font=("Microsoft YaHei", 9))
    before_path_lbl.pack(anchor="w", padx=8, pady=(2, 0))
    btn_row = tk.Frame(before_info_frame, bg=CARD_BG)
    btn_row.pack(anchor="e", padx=8, pady=8)
    tk.Button(btn_row, text="🗑 移除", bg=CARD_BG, fg=TEXT_DIM, bd=0, cursor="hand2", command=remove_before, font=("Microsoft YaHei", 9)).pack(side="right", padx=4)
    tk.Button(btn_row, text="📂 浏览...", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2", command=browse_before, font=("Microsoft YaHei", 9)).pack(side="right", padx=4)

    # ── After 卡片 ──
    after_card = tk.Frame(drop_area, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=2)
    after_card.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)

    after_drop_frame = tk.Frame(after_card, bg=CARD_BG)
    after_drop_frame.pack(fill="both", expand=True)
    after_drop_frame.drop_target_register(DND_FILES)
    after_drop_frame.dnd_bind("<<Drop>>", on_drop_after)

    tk.Label(after_drop_frame, text="➡ After（新版本）", bg=CARD_BG, fg=TEXT_DIM, font=("Microsoft YaHei", 10, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
    tk.Label(after_drop_frame, text="拖入新版本 .prefab", bg=CARD_BG, fg=TEXT_DIM, font=("Microsoft YaHei", 11)).pack(expand=True)
    tk.Label(after_drop_frame, text="或点击选择文件", bg=CARD_BG, fg=TEXT_DARK, font=("Microsoft YaHei", 9)).pack()
    tk.Button(after_drop_frame, text="📂 浏览...", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2", command=browse_after, font=("Microsoft YaHei", 9)).pack(pady=8)

    after_info_frame = tk.Frame(after_card, bg=CARD_BG)
    tk.Label(after_info_frame, text="➡ After（新版本）", bg=CARD_BG, fg=TEXT_DIM, font=("Microsoft YaHei", 10, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
    after_name_lbl = tk.Label(after_info_frame, text="", bg=CARD_BG, fg=TEXT, font=("Microsoft YaHei", 10, "bold"))
    after_name_lbl.pack(anchor="w", padx=8, pady=(4, 0))
    after_meta_lbl = tk.Label(after_info_frame, text="", bg=CARD_BG, fg=TEXT_DIM, font=("Microsoft YaHei", 9))
    after_meta_lbl.pack(anchor="w", padx=8)
    after_path_lbl = tk.Label(after_info_frame, text="", bg=CARD_BG, fg=TEXT_DARK, font=("Microsoft YaHei", 9))
    after_path_lbl.pack(anchor="w", padx=8, pady=(2, 0))
    btn_row2 = tk.Frame(after_info_frame, bg=CARD_BG)
    btn_row2.pack(anchor="e", padx=8, pady=8)
    tk.Button(btn_row2, text="🗑 移除", bg=CARD_BG, fg=TEXT_DIM, bd=0, cursor="hand2", command=remove_after, font=("Microsoft YaHei", 9)).pack(side="right", padx=4)
    tk.Button(btn_row2, text="📂 浏览...", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2", command=browse_after, font=("Microsoft YaHei", 9)).pack(side="right", padx=4)

    # 操作按钮
    action_bar = tk.Frame(parent, bg=BG)
    action_bar.pack(fill="x", padx=16, pady=8)
    gen_btn = tk.Button(action_bar, text="请先拖入两个 prefab", bg=BORDER, fg=TEXT_DIM, bd=0, padx=20, pady=6, cursor="hand2", state="disabled", command=do_generate, font=("Microsoft YaHei", 10, "bold"))
    gen_btn.pack(side="left")
    view_btn = tk.Button(action_bar, text="👁 查看树形报告", bg="#1e40af", fg=TEXT, bd=0, padx=16, pady=6, cursor="hand2", state="disabled", font=("Microsoft YaHei", 10, "bold"))
    view_btn.pack(side="left", padx=8)


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
    analyze_all_btn = tk.Button(head_bar, text="🔍 全部分析", bg="#1e40af", fg=TEXT, bd=0, padx=14, pady=4,
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

    _scroll_canvases.append(conflict_canvas)

    _populate_conflict_rows([])


_scroll_canvases: list = []  # 支持鼠标滚轮的 Canvas 列表（冲突组列表、最近报告列表）


def _clamp_scrollregion(canvas):
    """滚动区域夹紧到内容大小；内容不足一屏时撑满视口高度，使列表不可滚动"""
    bbox = canvas.bbox("all")
    content_w = bbox[2] if bbox else 0
    content_h = bbox[3] if bbox else 0
    view_h = max(canvas.winfo_height(), 1)
    canvas.configure(scrollregion=(0, 0, content_w, max(content_h, view_h)))
    if content_h <= view_h:
        canvas.yview_moveto(0)


def _update_scroll_region():
    # 等布局完成后再取 bbox，避免拿到重建前的旧尺寸
    conflict_canvas.after_idle(lambda: _clamp_scrollregion(conflict_canvas))


def _on_mousewheel(event):
    # 滚动鼠标所在的那个列表；内容不足一屏时不滚动
    w = root.winfo_containing(event.x_root, event.y_root)
    while w is not None:
        if w in _scroll_canvases:
            if w.yview() != (0.0, 1.0):
                w.yview_scroll(int(-event.delta / 120), "units")
            return
        w = w.master


# ═══════════════════════════════════════
# 主窗口
# ═══════════════════════════════════════

def _on_tab_changed(event):
    """切换页签时，最近报告列表切换到对应目录"""
    global current_reports_dir
    idx = event.widget.index(event.widget.select())
    if idx == 1:
        current_reports_dir = CONFLICT_REPORTS_DIR
        recent_title_lbl.config(text="📁 最近生成的报告（冲突分析）")
    else:
        current_reports_dir = COMPARE_REPORTS_DIR
        recent_title_lbl.config(text="📁 最近生成的报告（两方对比）")
    load_recent_reports()


def build_app():
    """构建主窗口及全部子控件，但不进入事件循环。

    返回根窗口。拆出此函数是为了让无头测试能构建完整 UI 并驱动回调，
    而不阻塞在 mainloop 上；run_gui 只是它加一句 mainloop 的薄封装。
    """
    global root, status_lbl, recent_frame, recent_title_lbl, recent_canvas, notebook

    root = TkinterDnD.Tk()
    root.title("PfbDiff 预制体对比工具")
    root.geometry("920x760")
    root.configure(bg=BG)

    _icon_path = _get_resource_path("icon.ico")
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
              background=[("selected", "#1e3a5f")],
              foreground=[("selected", TEXT)])
    style.configure("Vertical.TScrollbar", background=BORDER, troughcolor=CARD_BG, borderwidth=0)

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=16, pady=(0, 4))

    tab_compare = tk.Frame(notebook, bg=BG)
    tab_conflict = tk.Frame(notebook, bg=BG)
    notebook.add(tab_compare, text="  📊 两方对比  ")
    notebook.add(tab_conflict, text="  🌲 SVN 冲突分析  ")

    _build_compare_tab(tab_compare)
    _build_conflict_tab(tab_conflict)
    notebook.bind("<<NotebookTabChanged>>", _on_tab_changed)

    # 状态栏
    status_lbl = tk.Label(root, text="就绪", bg=BG, fg=TEXT_DARK, font=("Microsoft YaHei", 9))
    status_lbl.pack(anchor="w", padx=16, pady=(0, 4))

    # 最近报告（两个页签共用，滚动列表）
    recent_container = tk.Frame(root, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
    recent_container.pack(fill="x", padx=16, pady=(0, 12))
    recent_title_lbl = tk.Label(recent_container, text="📁 最近生成的报告（两方对比）", bg=CARD_BG, fg=TEXT_DIM, font=("Microsoft YaHei", 10, "bold"))
    recent_title_lbl.pack(anchor="w", padx=8, pady=8)

    recent_body = tk.Frame(recent_container, bg=CARD_BG)
    recent_body.pack(fill="x", padx=4, pady=(0, 8))
    recent_canvas = tk.Canvas(recent_body, bg=CARD_BG, highlightthickness=0, height=150)
    recent_scrollbar = ttk.Scrollbar(recent_body, orient="vertical", command=recent_canvas.yview)
    recent_frame = tk.Frame(recent_canvas, bg=CARD_BG)

    recent_frame.bind("<Configure>", lambda e: recent_canvas.after_idle(lambda: _clamp_scrollregion(recent_canvas)))
    recent_window = recent_canvas.create_window((0, 0), window=recent_frame, anchor="nw")
    recent_canvas.bind("<Configure>", lambda e: (recent_canvas.itemconfig(recent_window, width=e.width),
                                                 recent_canvas.after_idle(lambda: _clamp_scrollregion(recent_canvas))))
    recent_canvas.configure(yscrollcommand=recent_scrollbar.set)

    recent_canvas.pack(side="left", fill="x", expand=True, padx=4)
    recent_scrollbar.pack(side="right", fill="y")
    _scroll_canvases.append(recent_canvas)

    root.bind_all("<MouseWheel>", _on_mousewheel)
    load_recent_reports()

    return root


def run_gui():
    build_app()
    root.mainloop()


if __name__ == "__main__":
    run_gui()
