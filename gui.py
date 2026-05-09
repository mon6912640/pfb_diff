#!/usr/bin/env python3
"""PfbDiff Tkinter Desktop App — 原生拖放，能获取完整文件路径"""

import os
import sys
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

# ── 常量 ──
REPORTS_DIR = os.path.join(_PROJECT_ROOT, "reports")

# ── 配色 ──
BG = "#0b1120"
CARD_BG = "#111827"
BORDER = "#334155"
TEXT = "#e2e8f0"
TEXT_DIM = "#94a3b8"
TEXT_DARK = "#64748b"
ACCENT = "#3b82f6"


class AppState:
    def __init__(self):
        self.before_file: str | None = None
        self.after_file: str | None = None
        self.before_name: str = ""
        self.after_name: str = ""
        self.before_path: str = ""
        self.after_path: str = ""


state = AppState()


# ── 工具 ──
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
        return {"ok": True, "node_count": len(doc.nodes)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _strip_path(raw: str) -> str:
    """tkinterdnd2 Windows 路径可能有 {} 包裹，去掉它"""
    raw = raw.strip()
    if raw.startswith("{") and raw.endswith("}"):
        raw = raw[1:-1]
    return raw


# ── 拖放处理 ──
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


# ── 浏览按钮 ──
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


# ── 移除 ──
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


# ── UI 更新 ──
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


# ── 生成报告 ──
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
        view_btn.config(state="normal", command=lambda: webbrowser.open(f"file://{os.path.abspath(paths['html'])}"))
        load_recent_reports()
        messagebox.showinfo("完成", "报告生成成功")
    except Exception as e:
        messagebox.showerror("失败", f"生成失败: {e}")
        status_lbl.config(text="❌ 生成失败")
    finally:
        check_ready()


# ── 最近报告 ──
def load_recent_reports():
    for widget in recent_frame.winfo_children():
        widget.destroy()

    _ensure_reports_dir()
    files = []
    for f in os.listdir(REPORTS_DIR):
        if f.endswith(".html"):
            p = os.path.join(REPORTS_DIR, f)
            files.append((p, os.path.getmtime(p)))
    files.sort(key=lambda x: x[1], reverse=True)

    if not files:
        tk.Label(recent_frame, text="暂无报告", bg=BG, fg=TEXT_DARK, font=("Microsoft YaHei", 10)).pack(pady=10)
        return

    for path, mtime in files[:8]:
        name = os.path.basename(path)
        t = time.strftime("%m-%d %H:%M", time.localtime(mtime))
        row = tk.Frame(recent_frame, bg=CARD_BG)
        row.pack(fill="x", padx=4, pady=2)
        tk.Label(row, text=name, bg=CARD_BG, fg=TEXT, font=("Microsoft YaHei", 9, "bold")).pack(side="left")
        tk.Label(row, text=t, bg=CARD_BG, fg=TEXT_DARK, font=("Microsoft YaHei", 9)).pack(side="left", padx=8)
        tk.Button(
            row, text="👁", bg=CARD_BG, fg=ACCENT, bd=0,
            command=lambda p=path: webbrowser.open(f"file://{os.path.abspath(p)}"),
        ).pack(side="right")
        tk.Button(
            row, text="📂", bg=CARD_BG, fg=TEXT_DIM, bd=0,
            command=lambda p=path: os.startfile(os.path.dirname(p)),
        ).pack(side="right", padx=4)


def _get_resource_path(rel: str) -> str:
    """兼容 PyInstaller 打包后的资源路径"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel)
    return os.path.join(_PROJECT_ROOT, rel)


# ═══════════════════════════════════════
# 主窗口
# ═══════════════════════════════════════
def run_gui():
    global root, before_drop_frame, before_info_frame, before_name_lbl, before_meta_lbl, before_path_lbl
    global after_drop_frame, after_info_frame, after_name_lbl, after_meta_lbl, after_path_lbl
    global gen_btn, view_btn, status_lbl, recent_frame

    root = TkinterDnD.Tk()
    root.title("PfbDiff 预制体对比工具")
    root.geometry("900x700")
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

    # 左右拖放区
    drop_area = tk.Frame(root, bg=BG)
    drop_area.pack(fill="both", expand=True, padx=16, pady=8)
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
    action_bar = tk.Frame(root, bg=BG)
    action_bar.pack(fill="x", padx=16, pady=8)
    gen_btn = tk.Button(action_bar, text="请先拖入两个 prefab", bg=BORDER, fg=TEXT_DIM, bd=0, padx=20, pady=6, cursor="hand2", state="disabled", command=do_generate, font=("Microsoft YaHei", 10, "bold"))
    gen_btn.pack(side="left")
    view_btn = tk.Button(action_bar, text="👁 查看树形报告", bg="#1e40af", fg=TEXT, bd=0, padx=16, pady=6, cursor="hand2", state="disabled", font=("Microsoft YaHei", 10, "bold"))
    view_btn.pack(side="left", padx=8)

    # 状态栏
    status_lbl = tk.Label(root, text="就绪", bg=BG, fg=TEXT_DARK, font=("Microsoft YaHei", 9))
    status_lbl.pack(anchor="w", padx=16, pady=(0, 4))

    # 最近报告
    recent_container = tk.Frame(root, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
    recent_container.pack(fill="both", expand=True, padx=16, pady=8)
    tk.Label(recent_container, text="📁 最近生成的报告", bg=CARD_BG, fg=TEXT_DIM, font=("Microsoft YaHei", 10, "bold")).pack(anchor="w", padx=8, pady=8)
    recent_frame = tk.Frame(recent_container, bg=CARD_BG)
    recent_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
    load_recent_reports()

    root.mainloop()


if __name__ == "__main__":
    run_gui()
