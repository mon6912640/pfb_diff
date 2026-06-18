#!/usr/bin/env python3
"""PfbDiff GUI — 「🌲 SVN 冲突分析」页签。

拖入 .prefab.working 冲突文件（自动定位同组 base/ours/theirs）或整个目录
批量扫描。分析在后台线程进行，所有 UI 更新通过 root.after 回主线程。
冲突组列表状态与控件全部封装在 ConflictTab 实例里。
"""

import os
import threading

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from tkinterdnd2 import DND_FILES

from svn_conflict_helper import find_conflict_groups, find_group_by_working, analyze_conflict, generate_reports

from gui_shell import AppShell, CONFLICT_REPORTS_DIR, ensure_dir, strip_path, clamp_scrollregion
from gui_theme import (
    BG, CARD_BG, BORDER, TEXT, TEXT_DIM, TEXT_DARK, ACCENT, RED, GREEN, YELLOW,
    PRIMARY_BTN_BG, FONT_FAMILY,
)


class ConflictTab:
    """SVN 冲突分析页签：自带冲突组列表与后台分析，依赖 AppShell 提供状态栏/最近报告/打开报告。"""

    def __init__(self, shell: AppShell, parent: tk.Misc):
        self.shell = shell
        self.rows: list = []     # [{group, name, status, error, overview, summary, auto_open, widgets...}]
        self.busy = False
        self._build(parent)

    # ── 拖放 / 选择 ──
    def on_drop(self, event):
        path = strip_path(event.data)
        if os.path.isdir(path):
            self.load_dir(path)
        elif path.endswith(".working"):
            self.load_working(path)
        else:
            messagebox.showwarning(
                "格式错误",
                "请拖入 .prefab.working 冲突文件，或包含冲突文件的目录\n当前: " + path,
            )

    def browse_file(self):
        path = filedialog.askopenfilename(filetypes=[("SVN 冲突文件", "*.working"), ("所有文件", "*.*")])
        if path:
            self.load_working(path)

    def browse_dir(self):
        path = filedialog.askdirectory()
        if path:
            self.load_dir(path)

    def load_working(self, path: str):
        """单个 .working 文件：自动定位同组文件，立即分析并打开概览"""
        if self.busy:
            messagebox.showinfo("提示", "正在分析中，请稍候")
            return
        try:
            group = find_group_by_working(path)
        except ValueError as e:
            messagebox.showerror("无法定位冲突组", str(e))
            return
        self._populate_rows([{"group": group, "name": group["name"], "status": "ready"}])
        self.hint_lbl.config(text=f"已定位冲突组（来自 {os.path.basename(path)}）")
        self._start_jobs([0], auto_open=True)

    def load_dir(self, path: str):
        """目录：扫描所有冲突组，等用户确认后分析"""
        if self.busy:
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
            self.hint_lbl.config(text=f"未在 {path} 发现 SVN 冲突文件组")
            self._populate_rows([])
            return

        self._populate_rows(rows)
        self.hint_lbl.config(
            text=f"在 {os.path.basename(path) or path} 发现 {len(groups)} 个冲突组"
                 + (f"，{len(orphans)} 个缺少文件" if orphans else "")
        )

    # ── 列表渲染 ──
    def _populate_rows(self, rows: list):
        """重建冲突组列表 UI"""
        self.rows = rows
        for w in self.list_frame.winfo_children():
            w.destroy()

        if not rows:
            tk.Label(self.list_frame, text="拖入冲突文件或目录后，这里会列出冲突组",
                     bg=CARD_BG, fg=TEXT_DARK, font=(FONT_FAMILY, 9)).pack(pady=16)
            self.analyze_all_btn.config(state="disabled")
            self._update_scroll_region()  # 清空后必须重设滚动区域，否则残留上一次的可滚动高度
            return

        for i, row in enumerate(rows):
            frame = tk.Frame(self.list_frame, bg=CARD_BG)
            frame.pack(fill="x", padx=4, pady=2)

            tk.Label(frame, text=row["name"], bg=CARD_BG, fg=TEXT,
                     font=(FONT_FAMILY, 9, "bold")).pack(side="left")

            status_lbl_w = tk.Label(frame, text="", bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 9))
            status_lbl_w.pack(side="left", padx=8)

            summary_lbl_w = tk.Label(frame, text="", bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 9))
            summary_lbl_w.pack(side="left", padx=4)

            view_btn_w = tk.Button(frame, text="👁 查看概览", bg=CARD_BG, fg=ACCENT, bd=0,
                                   cursor="hand2", state="disabled", font=(FONT_FAMILY, 9))
            view_btn_w.pack(side="right", padx=4)

            analyze_btn_w = tk.Button(frame, text="🔍 分析", bg=CARD_BG, fg=ACCENT, bd=0,
                                      cursor="hand2", font=(FONT_FAMILY, 9),
                                      command=lambda i=i: self._start_jobs([i]))
            analyze_btn_w.pack(side="right", padx=4)

            row["w_status"] = status_lbl_w
            row["w_summary"] = summary_lbl_w
            row["w_view"] = view_btn_w
            row["w_analyze"] = analyze_btn_w
            self._render_row(i)

        has_ready = any(r["status"] == "ready" for r in rows)
        self.analyze_all_btn.config(state="normal" if has_ready else "disabled")
        self._update_analyze_all_text()
        self._update_scroll_region()

    def _render_row(self, i: int):
        row = self.rows[i]
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
            row["w_view"].config(state="normal", command=lambda p=row["overview"]: self.shell.open_report(p))
        elif row["status"] == "error":
            row["w_summary"].config(text=row.get("error", ""), fg=RED)

    def _update_analyze_all_text(self):
        """全部分析按钮文案：列表里还有没分析过的→全部分析；全都跑过了→重新全部分析"""
        actionable = [r for r in self.rows if r["status"] != "missing"]
        if actionable and all(r["status"] in ("done", "error") for r in actionable):
            self.analyze_all_btn.config(text="🔄 重新全部分析")
        else:
            self.analyze_all_btn.config(text="🔍 全部分析")

    def _set_controls(self, enabled: bool):
        state_str = "normal" if enabled else "disabled"
        self.analyze_all_btn.config(
            state=state_str if any(r["status"] != "missing" for r in self.rows) else "disabled")
        for r in self.rows:
            if r["status"] != "missing":
                r["w_analyze"].config(state=state_str)
        self._update_analyze_all_text()

    # ── 后台分析 ──
    def analyze_all(self):
        self._start_jobs([i for i, r in enumerate(self.rows) if r["status"] in ("ready", "error", "done")])

    def _start_jobs(self, indices: list, auto_open: bool = False):
        if self.busy or not indices:
            return
        jobs = [i for i in indices if self.rows[i]["status"] != "missing"]
        if not jobs:
            return
        self.busy = True
        self._set_controls(False)
        for i in jobs:
            self.rows[i]["status"] = "queued"
            self.rows[i]["auto_open"] = auto_open
            self._render_row(i)
        threading.Thread(target=self._worker, args=(jobs,), daemon=True).start()

    def _worker(self, jobs: list):
        """后台线程：逐组分析。所有 UI 更新通过 root.after 回主线程。"""
        root = self.shell.root
        ensure_dir(CONFLICT_REPORTS_DIR)
        for i in jobs:
            row = self.rows[i]
            root.after(0, self._on_row_running, i)
            try:
                data = analyze_conflict(
                    row["group"],
                    progress=lambda m: root.after(0, self.shell.set_status, m.strip()),
                )
                overview = generate_reports(data, CONFLICT_REPORTS_DIR, progress=lambda m: None)
                root.after(0, self._on_row_done, i, data["summary"], overview)
            except Exception as e:
                root.after(0, self._on_row_fail, i, str(e))
        root.after(0, self._on_all_done)

    def _on_row_running(self, i: int):
        self.rows[i]["status"] = "running"
        self._render_row(i)

    def _on_row_done(self, i: int, summary: dict, overview: str):
        row = self.rows[i]
        row["status"] = "done"
        row["summary"] = summary
        row["overview"] = overview
        self._render_row(i)
        if row.get("auto_open"):
            self.shell.open_report(overview)

    def _on_row_fail(self, i: int, error: str):
        self.rows[i]["status"] = "error"
        self.rows[i]["error"] = error
        self._render_row(i)

    def _on_all_done(self):
        self.busy = False
        self._set_controls(True)
        done = sum(1 for r in self.rows if r["status"] == "done")
        failed = sum(1 for r in self.rows if r["status"] == "error")
        self.shell.set_status(f"✅ 冲突分析完成 {done} 组" + (f"，失败 {failed} 组" if failed else ""))
        self.shell.load_recent_reports()

    def _update_scroll_region(self):
        # 等布局完成后再取 bbox，避免拿到重建前的旧尺寸
        self.canvas.after_idle(lambda: clamp_scrollregion(self.canvas))

    # ── 构建 ──
    def _build(self, parent: tk.Misc):
        # ── 拖放区 ──
        drop_card = tk.Frame(parent, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=2)
        drop_card.pack(fill="x", padx=16, pady=(16, 8))
        drop_card.drop_target_register(DND_FILES)
        drop_card.dnd_bind("<<Drop>>", self.on_drop)

        tk.Label(drop_card, text="🌲 拖入 .prefab.working 冲突文件（自动定位同组并分析）",
                 bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 11)).pack(pady=(14, 0))
        tk.Label(drop_card, text="或拖入整个目录，自动扫描所有 SVN 冲突组",
                 bg=CARD_BG, fg=TEXT_DARK, font=(FONT_FAMILY, 9)).pack()
        btn_bar = tk.Frame(drop_card, bg=CARD_BG)
        btn_bar.pack(pady=(4, 12))
        tk.Button(btn_bar, text="📂 选择 .working 文件", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2",
                  command=self.browse_file, font=(FONT_FAMILY, 9)).pack(side="left", padx=8)
        tk.Button(btn_bar, text="📁 选择目录扫描", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2",
                  command=self.browse_dir, font=(FONT_FAMILY, 9)).pack(side="left", padx=8)

        # ── 列表头 ──
        head_bar = tk.Frame(parent, bg=BG)
        head_bar.pack(fill="x", padx=16, pady=(8, 0))
        self.hint_lbl = tk.Label(head_bar, text="尚未加载冲突文件", bg=BG, fg=TEXT_DIM, font=(FONT_FAMILY, 9))
        self.hint_lbl.pack(side="left")
        self.analyze_all_btn = tk.Button(head_bar, text="🔍 全部分析", bg=PRIMARY_BTN_BG, fg=TEXT, bd=0, padx=14, pady=4,
                                         cursor="hand2", state="disabled", command=self.analyze_all,
                                         font=(FONT_FAMILY, 9, "bold"))
        self.analyze_all_btn.pack(side="right")

        # ── 冲突组列表（可滚动）──
        list_container = tk.Frame(parent, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        list_container.pack(fill="both", expand=True, padx=16, pady=8)

        self.canvas = tk.Canvas(list_container, bg=CARD_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=self.canvas.yview)
        self.list_frame = tk.Frame(self.canvas, bg=CARD_BG)

        self.list_frame.bind("<Configure>", lambda e: self._update_scroll_region())
        canvas_window = self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: (self.canvas.itemconfig(canvas_window, width=e.width),
                                                   self._update_scroll_region()))
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        scrollbar.pack(side="right", fill="y")

        self.shell.register_scroll(self.canvas)

        self._populate_rows([])
