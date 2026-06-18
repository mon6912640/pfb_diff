#!/usr/bin/env python3
"""PfbDiff GUI — 「📜 版本对比」页签（同一文件、同分支的两个版本）。

拖入 SVN 工作副本内的 .prefab，从其历史里选两个端点对比；每个端点可以是
某个 revision，或「当前工作副本（含未提交改动）」。覆盖历史考古（rev↔rev）
与提交/合并前自检（工作副本↔rev）两种高频场景。

取数走 svn_revision_helper（后台线程），对比与报告复用 diff_engine /
report_html_tree，UI 框架复用 AppShell。
"""

import os
import shutil
import threading
import time

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from tkinterdnd2 import DND_FILES

import svn_revision_helper as svnh
from diff_engine import diff_prefabs
from report_html_tree import write_html_report as write_tree_report
from report_json import write_json_report

from gui_shell import AppShell, REVISION_REPORTS_DIR, ensure_dir, safe_name, strip_path
from gui_theme import (
    BG, CARD_BG, BORDER, TEXT, TEXT_DIM, TEXT_DARK, ACCENT, PRIMARY_BTN_BG, FONT_FAMILY,
)

# 「工作副本」端点的占位（不 cat，直接用 WC 文件本身）
_WORKING = ("working", None)


class RevisionTab:
    def __init__(self, shell: AppShell, parent: tk.Misc):
        self.shell = shell
        self.file = None          # 拖入的 WC 文件路径
        self.specs: list = []     # 与下拉项对齐：[("working",None), ("rev",N), ...]
        self.busy = False
        self._build(parent)

    # ── 加载文件 ──
    def on_drop(self, event):
        self._load(strip_path(event.data))

    def browse(self):
        path = filedialog.askopenfilename(filetypes=[("Prefab files", "*.prefab")])
        if path:
            self._load(path)

    def _load(self, path: str):
        if not path.lower().endswith(".prefab"):
            messagebox.showwarning("格式错误", f"请选择 .prefab 文件\n当前: {path}")
            return
        if not svnh.svn_available():
            messagebox.showerror("缺少 svn", "未找到 svn 命令，请先安装 SVN 命令行客户端并加入 PATH")
            return
        try:
            meta = svnh.info(path)
            entries = svnh.log(path)
        except svnh.SvnError as e:
            messagebox.showerror("无法读取 svn 信息", f"{e}\n\n该文件需位于 SVN 工作副本内。")
            return

        self.file = path
        self.specs = [_WORKING] + [("rev", e["rev"]) for e in entries]
        options = ["工作副本（含未提交改动）"] + [
            f"r{e['rev']}  {e['date']}  {e['msg'][:30]}" for e in entries
        ]
        self.left_cb.config(values=options)
        self.right_cb.config(values=options)
        # 默认：左=最新提交版本，右=工作副本（即"自上次提交以来改了啥"）
        self.left_cb.current(1 if len(options) > 1 else 0)
        self.right_cb.current(0)

        self.info_lbl.config(text=f"{os.path.basename(path)} @ r{meta['rev']}  ·  {meta['url']}")
        self.drop_frame.pack_forget()
        self.body_frame.pack(fill="x", padx=8, pady=8)
        self.compare_btn.config(state="normal")

    # ── 对比 ──
    def do_compare(self):
        if self.busy or not self.file:
            return
        li, ri = self.left_cb.current(), self.right_cb.current()
        if li < 0 or ri < 0:
            return
        left_spec, right_spec = self.specs[li], self.specs[ri]
        if left_spec == right_spec:
            messagebox.showinfo("提示", "两个端点相同，无需对比")
            return
        self.busy = True
        self.compare_btn.config(state="disabled", text="⏳ 正在取版本并对比...")
        threading.Thread(target=self._worker, args=(left_spec, right_spec), daemon=True).start()

    def _resolve(self, spec, workdir, side) -> tuple:
        """把端点解析成 (文件路径, 标签)。工作副本端直接用 WC 文件，不 cat。"""
        kind, rev = spec
        if kind == "working":
            return self.file, "working"
        dest = os.path.join(workdir, f"{side}.prefab")
        svnh.cat(self.file, rev, dest)
        return dest, f"r{rev}"

    def _worker(self, left_spec, right_spec):
        root = self.shell.root
        work = svnh.make_workdir()
        try:
            left_path, left_label = self._resolve(left_spec, work, "left")
            right_path, right_label = self._resolve(right_spec, work, "right")
            result = diff_prefabs(left_path, right_path)
            base = os.path.basename(self.file)
            result.before_path = f"{base}@{left_label}"
            result.after_path = f"{base}@{right_label}"

            ensure_dir(REVISION_REPORTS_DIR)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            name = f"{safe_name(base)}_{left_label}_vs_{right_label}_{stamp}"
            html = os.path.join(REVISION_REPORTS_DIR, name + ".html")
            write_tree_report(result, html)
            write_json_report(result, os.path.join(REVISION_REPORTS_DIR, name + ".json"))
            root.after(0, self._on_done, html)
        except Exception as e:
            root.after(0, self._on_fail, str(e))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _on_done(self, html: str):
        self.busy = False
        self.compare_btn.config(state="normal", text="🔍 生成版本对比报告")
        self.shell.set_status(f"✅ 已完成: {os.path.basename(html)}")
        self.view_btn.config(state="normal", command=lambda: self.shell.open_report(html))
        self.shell.load_recent_reports()
        self.shell.open_report(html)

    def _on_fail(self, error: str):
        self.busy = False
        self.compare_btn.config(state="normal", text="🔍 生成版本对比报告")
        self.shell.set_status("❌ 对比失败")
        messagebox.showerror("对比失败", error)

    # ── 构建 ──
    def _build(self, parent: tk.Misc):
        card = tk.Frame(parent, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=2)
        card.pack(fill="x", padx=16, pady=(16, 8))

        # 未加载文件时显示的拖放区
        self.drop_frame = tk.Frame(card, bg=CARD_BG)
        self.drop_frame.pack(fill="both", expand=True)
        self.drop_frame.drop_target_register(DND_FILES)
        self.drop_frame.dnd_bind("<<Drop>>", self.on_drop)
        tk.Label(self.drop_frame, text="📜 拖入 SVN 工作副本内的 .prefab（选两个版本对比）",
                 bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 11)).pack(pady=(16, 0))
        tk.Label(self.drop_frame, text="每个端点可选某个 revision，或当前工作副本（含未提交改动）",
                 bg=CARD_BG, fg=TEXT_DARK, font=(FONT_FAMILY, 9)).pack()
        tk.Button(self.drop_frame, text="📂 选择文件", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2",
                  command=self.browse, font=(FONT_FAMILY, 9)).pack(pady=(4, 16))

        # 加载文件后显示的版本选择区
        self.body_frame = tk.Frame(card, bg=CARD_BG)
        self.info_lbl = tk.Label(self.body_frame, text="", bg=CARD_BG, fg=TEXT, font=(FONT_FAMILY, 9, "bold"))
        self.info_lbl.pack(anchor="w", padx=8, pady=(8, 6))

        row = tk.Frame(self.body_frame, bg=CARD_BG)
        row.pack(fill="x", padx=8, pady=(0, 4))
        tk.Label(row, text="旧（before）", bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 9)).pack(side="left")
        self.left_cb = ttk.Combobox(row, state="readonly", width=46)
        self.left_cb.pack(side="left", padx=8)

        row2 = tk.Frame(self.body_frame, bg=CARD_BG)
        row2.pack(fill="x", padx=8, pady=(0, 8))
        tk.Label(row2, text="新（after）", bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 9)).pack(side="left")
        self.right_cb = ttk.Combobox(row2, state="readonly", width=46)
        self.right_cb.pack(side="left", padx=8)

        tk.Button(self.body_frame, text="🔄 换个文件", bg=CARD_BG, fg=TEXT_DIM, bd=0, cursor="hand2",
                  command=self.browse, font=(FONT_FAMILY, 9)).pack(anchor="e", padx=8, pady=(0, 8))

        # 操作按钮
        action = tk.Frame(parent, bg=BG)
        action.pack(fill="x", padx=16, pady=8)
        self.compare_btn = tk.Button(action, text="🔍 生成版本对比报告", bg=PRIMARY_BTN_BG, fg=TEXT, bd=0,
                                     padx=20, pady=6, cursor="hand2", state="disabled",
                                     command=self.do_compare, font=(FONT_FAMILY, 10, "bold"))
        self.compare_btn.pack(side="left")
        self.view_btn = tk.Button(action, text="👁 查看报告", bg=PRIMARY_BTN_BG, fg=TEXT, bd=0,
                                  padx=16, pady=6, cursor="hand2", state="disabled",
                                  font=(FONT_FAMILY, 10, "bold"))
        self.view_btn.pack(side="left", padx=8)
