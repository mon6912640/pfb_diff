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
from prefab_parser import parse_prefab
from report_html_tree import write_html_report as write_tree_report
from report_json import write_json_report

from gui_shell import AppShell, REVISION_REPORTS_DIR, ensure_dir, safe_name, strip_path
from gui_theme import (
    BG, CARD_BG, BORDER, TEXT, TEXT_DIM, TEXT_DARK, ACCENT, PRIMARY_BTN_BG, FONT_FAMILY,
)


def _parse_info(file_path: str) -> dict:
    try:
        doc = parse_prefab(file_path)
        return {"ok": True, "node_count": len(doc.nodes)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# 「工作副本」端点的占位（不 cat，直接用 WC 文件本身）
_WORKING = ("working", None)


class RevisionTab:
    def __init__(self, shell: AppShell, parent: tk.Misc):
        self.shell = shell
        self.file = None          # 拖入的 WC 文件路径
        self.meta = None          # svn info 结果
        self.entries: list = []   # svn log 返回的原始条目
        self.specs: list = []     # 与下拉项对齐：[("working",None), ("rev",N), ...]
        self.options: list = []   # 下拉框显示文本
        self.busy = False         # 正在生成报告
        self.loading = False      # 正在读取 SVN 历史
        self._pending_path: str | None = None
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

        self._pending_path = path
        self._show_file_loading()
        self.loading = True
        self._refresh_controls()
        threading.Thread(target=self._load_worker, args=(path,), daemon=True).start()

    def _load_worker(self, path: str):
        try:
            meta = svnh.info(path)
            entries = svnh.log(path)
            info = _parse_info(path)
            self.shell.root.after(0, self._on_loaded, path, meta, entries, info)
        except Exception as e:
            self.shell.root.after(0, self._on_failed, path, str(e))

    def _on_loaded(self, path: str, meta: dict, entries: list, info: dict):
        if self._pending_path != path:
            return  # 加载过程中已被清除/覆盖，忽略过期回调
        self._pending_path = None
        self.loading = False

        self.file = path
        self.meta = meta
        self.entries = entries
        self.specs = [_WORKING] + [("rev", e["rev"]) for e in entries]
        self.options = ["工作副本（含未提交改动）"] + [
            f"r{e['rev']}  {e['date']}  {e['msg'][:30]}" for e in entries
        ]

        self.left_cb.config(values=self.options)
        self.right_cb.config(values=self.options)
        # 默认：左=最新提交版本，右=工作副本（即"自上次提交以来改了啥"）
        self.left_cb.current(1 if len(self.options) > 1 else 0)
        self.right_cb.current(0)

        self._update_file_banner(info)
        self._update_meta_labels()
        self._refresh_controls()
        self._check_ready()

    def _on_failed(self, path: str, error: str):
        if self._pending_path != path:
            return
        self._pending_path = None
        self.loading = False
        self._clear_file()
        self.shell.set_status("❌ 文件加载失败")
        messagebox.showerror("加载失败", error)

    def _clear_file(self):
        self._pending_path = None
        self.file = None
        self.meta = None
        self.entries = []
        self.specs = []
        self.options = []
        self.left_cb.config(values=[])
        self.right_cb.config(values=[])
        self._update_file_banner()
        self._update_meta_labels()
        self._refresh_controls()
        self._check_ready()

    def _show_file_loading(self):
        self.file_drop_frame.pack_forget()
        self.file_info_frame.pack(fill="both", expand=True, padx=8, pady=8)
        self.file_name_lbl.config(text="⏳ 正在读取 SVN 历史...", fg=ACCENT)
        self.file_url_lbl.config(text="")
        self.file_meta_lbl.config(text="")
        self.left_cb.config(values=[])
        self.right_cb.config(values=[])

    def _update_file_banner(self, info: dict | None = None):
        if self.file:
            if info is None:
                info = _parse_info(self.file)
            self.file_name_lbl.config(text=os.path.basename(self.file), fg=TEXT)
            self.file_url_lbl.config(text=f"r{self.meta['rev']}  ·  {self.meta['url']}")
            if info["ok"]:
                self.file_meta_lbl.config(text=f"📄 {info['node_count']} 节点")
            else:
                self.file_meta_lbl.config(text=f"⚠️ {info['error']}")
            self.file_drop_frame.pack_forget()
            self.file_info_frame.pack(fill="both", expand=True, padx=8, pady=8)
        else:
            self.file_name_lbl.config(text="", fg=TEXT)
            self.file_url_lbl.config(text="")
            self.file_meta_lbl.config(text="")
            self.file_info_frame.pack_forget()
            self.file_drop_frame.pack(fill="both", expand=True, padx=8, pady=8)

    # ── 版本选择 ──
    def _on_version_changed(self, _event=None):
        self._update_meta_labels()
        self._check_ready()

    def _update_meta_labels(self):
        self._render_meta(self.left_cb, self.left_meta_lbl)
        self._render_meta(self.right_cb, self.right_meta_lbl)

    def _render_meta(self, cb: ttk.Combobox, lbl: tk.Label):
        idx = cb.current()
        if idx < 0 or idx >= len(self.specs):
            lbl.config(text="", fg=TEXT_DARK)
            return
        kind, rev = self.specs[idx]
        if kind == "working":
            lbl.config(text="当前工作副本（含未提交改动）", fg=ACCENT)
        else:
            entry = self.entries[idx - 1]   # specs[0] 是 working，entries 从 specs[1] 对应
            msg = entry["msg"].replace("\n", " ").replace("\r", " ").strip()
            if len(msg) > 120:
                msg = msg[:120] + "..."
            lbl.config(
                text=f"{entry['date']}  ·  {entry.get('author', 'unknown')}  ·  {msg}",
                fg=TEXT_DIM,
            )

    def _swap_versions(self):
        if self.busy or self.loading or not self.file:
            return
        li, ri = self.left_cb.current(), self.right_cb.current()
        if li < 0 or ri < 0:
            return
        self.left_cb.current(ri)
        self.right_cb.current(li)
        self._update_meta_labels()
        self._check_ready()

    # ── 对比 ──
    def do_compare(self):
        if self.busy or self.loading or not self.file:
            return
        li, ri = self.left_cb.current(), self.right_cb.current()
        if li < 0 or ri < 0:
            return
        left_spec, right_spec = self.specs[li], self.specs[ri]
        if left_spec == right_spec:
            messagebox.showinfo("提示", "两个端点相同，无需对比")
            return
        self._set_controls(False)
        self.compare_btn.config(text="⏳ 正在取版本并对比...")
        threading.Thread(target=self._worker, args=(left_spec, right_spec), daemon=True).start()

    def _resolve(self, spec, workdir: str, side: str) -> tuple:
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
        self._set_controls(True)
        self.view_btn.config(state="normal", command=lambda: self.shell.open_report(html))
        self.shell.set_status(f"✅ 已完成: {os.path.basename(html)}")
        self.shell.load_recent_reports()
        self.shell.open_report(html)

    def _on_fail(self, error: str):
        self._set_controls(True)
        self.shell.set_status("❌ 对比失败")
        messagebox.showerror("对比失败", error)

    # ── 控件状态 ──
    def _set_controls(self, enabled: bool):
        """生成报告开始/结束时调用。"""
        self.busy = not enabled
        self._refresh_controls()
        self._check_ready()

    def _refresh_controls(self):
        """根据当前状态刷新 combobox / 交换按钮的启用状态。"""
        readonly = bool(self.file and not self.busy and not self.loading)
        self.left_cb.config(state="readonly" if readonly else "disabled")
        self.right_cb.config(state="readonly" if readonly else "disabled")
        self.swap_btn.config(state="normal" if readonly else "disabled")

    def _check_ready(self):
        li, ri = self.left_cb.current(), self.right_cb.current()
        ready = bool(
            self.file and li >= 0 and ri >= 0 and self.specs[li] != self.specs[ri]
            and not self.busy and not self.loading
        )
        self.compare_btn.config(
            state="normal" if ready else "disabled",
            text="🔍 生成版本对比报告" if ready else "请先选择文件与两个版本",
        )

    # ── 构建 ──
    def _build(self, parent: tk.Misc):
        # 文件横幅 + 左右两张版本卡片
        drop_area = tk.Frame(parent, bg=BG)
        drop_area.pack(fill="both", expand=True, padx=8, pady=8)
        drop_area.grid_columnconfigure(0, weight=1, uniform="version_cards")
        drop_area.grid_columnconfigure(1, weight=1, uniform="version_cards")
        drop_area.grid_rowconfigure(1, weight=1)

        # ── 顶部文件横幅 ──
        file_banner = tk.Frame(drop_area, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=2)
        file_banner.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))

        self.file_drop_frame = tk.Frame(file_banner, bg=CARD_BG)
        self.file_drop_frame.pack(fill="both", expand=True)
        self.file_drop_frame.drop_target_register(DND_FILES)
        self.file_drop_frame.dnd_bind("<<Drop>>", self.on_drop)

        tk.Label(self.file_drop_frame, text="📜 拖入 SVN 工作副本内的 .prefab",
                 bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 11)).pack(pady=(12, 0))
        tk.Label(self.file_drop_frame, text="选两个版本进行对比（revision ↔ revision，或 working ↔ revision）",
                 bg=CARD_BG, fg=TEXT_DARK, font=(FONT_FAMILY, 9)).pack()
        tk.Button(self.file_drop_frame, text="📂 选择文件", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2",
                  command=self.browse, font=(FONT_FAMILY, 9)).pack(pady=(4, 12))

        self.file_info_frame = tk.Frame(file_banner, bg=CARD_BG)
        self.file_name_lbl = tk.Label(self.file_info_frame, text="", bg=CARD_BG, fg=TEXT,
                                      font=(FONT_FAMILY, 10, "bold"))
        self.file_name_lbl.pack(anchor="w", padx=8, pady=(8, 0))
        self.file_url_lbl = tk.Label(self.file_info_frame, text="", bg=CARD_BG, fg=TEXT_DARK,
                                     font=(FONT_FAMILY, 9))
        self.file_url_lbl.pack(anchor="w", padx=8)
        file_bottom = tk.Frame(self.file_info_frame, bg=CARD_BG)
        file_bottom.pack(fill="x", padx=8, pady=(2, 8))
        self.file_meta_lbl = tk.Label(file_bottom, text="", bg=CARD_BG, fg=TEXT_DIM,
                                      font=(FONT_FAMILY, 9))
        self.file_meta_lbl.pack(side="left")
        tk.Button(file_bottom, text="🗑 清除", bg=CARD_BG, fg=TEXT_DIM, bd=0, cursor="hand2",
                  command=self._clear_file, font=(FONT_FAMILY, 9)).pack(side="right", padx=4)
        tk.Button(file_bottom, text="📂 浏览...", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2",
                  command=self.browse, font=(FONT_FAMILY, 9)).pack(side="right", padx=4)

        # ── 左侧卡片：旧版本（before）──
        left_card = tk.Frame(drop_area, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=2)
        left_card.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)

        tk.Label(left_card, text="⬅ 旧版本（before）", bg=CARD_BG, fg=TEXT_DIM,
                 font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
        left_row = tk.Frame(left_card, bg=CARD_BG)
        left_row.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(left_row, text="版本", bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 9)).pack(side="left")
        self.left_cb = ttk.Combobox(left_row, state="readonly")
        self.left_cb.pack(side="left", fill="x", expand=True, padx=8)
        self.left_cb.bind("<<ComboboxSelected>>", self._on_version_changed)
        self.left_meta_lbl = tk.Label(left_card, text="", bg=CARD_BG, fg=TEXT_DIM,
                                      font=(FONT_FAMILY, 9), wraplength=380, justify="left")
        self.left_meta_lbl.pack(fill="x", padx=8, pady=(0, 8))

        # ── 右侧卡片：新版本（after）──
        right_card = tk.Frame(drop_area, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=2)
        right_card.grid(row=1, column=1, sticky="nsew", padx=8, pady=8)

        tk.Label(right_card, text="➡ 新版本（after）", bg=CARD_BG, fg=TEXT_DIM,
                 font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
        right_row = tk.Frame(right_card, bg=CARD_BG)
        right_row.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(right_row, text="版本", bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 9)).pack(side="left")
        self.right_cb = ttk.Combobox(right_row, state="readonly")
        self.right_cb.pack(side="left", fill="x", expand=True, padx=8)
        self.right_cb.bind("<<ComboboxSelected>>", self._on_version_changed)
        self.right_meta_lbl = tk.Label(right_card, text="", bg=CARD_BG, fg=TEXT_DIM,
                                       font=(FONT_FAMILY, 9), wraplength=380, justify="left")
        self.right_meta_lbl.pack(fill="x", padx=8, pady=(0, 8))

        # 操作按钮
        action_bar = tk.Frame(parent, bg=BG)
        action_bar.pack(fill="x", padx=16, pady=8)
        self.compare_btn = tk.Button(action_bar, text="请先选择文件与两个版本", bg=BORDER, fg=TEXT_DIM,
                                     bd=0, padx=20, pady=6, cursor="hand2", state="disabled",
                                     command=self.do_compare, font=(FONT_FAMILY, 10, "bold"))
        self.compare_btn.pack(side="left")
        self.swap_btn = tk.Button(action_bar, text="🔃 交换", bg=CARD_BG, fg=ACCENT, bd=0,
                                  padx=14, pady=6, cursor="hand2", state="disabled",
                                  command=self._swap_versions, font=(FONT_FAMILY, 10, "bold"))
        self.swap_btn.pack(side="left", padx=8)
        self.view_btn = tk.Button(action_bar, text="👁 查看报告", bg=PRIMARY_BTN_BG, fg=TEXT, bd=0,
                                  padx=16, pady=6, cursor="hand2", state="disabled",
                                  font=(FONT_FAMILY, 10, "bold"))
        self.view_btn.pack(side="left", padx=8)
