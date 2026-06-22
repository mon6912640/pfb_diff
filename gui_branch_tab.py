#!/usr/bin/env python3
"""PfbDiff GUI — 「🌿 分支对比」页签。

左右两侧各自拖入一个 .prefab（可来自不同 SVN 分支 / 不同路径），分别列出
各自的 SVN 提交历史，各选一个端点（工作副本或某个 revision）进行对比。

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

from gui_shell import AppShell, BRANCH_REPORTS_DIR, ensure_dir, safe_name, strip_path
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


class BranchTab:
    def __init__(self, shell: AppShell, parent: tk.Misc):
        self.shell = shell
        self.busy = False          # 正在生成报告
        self.left_loading = False  # 正在读取左侧 SVN 历史
        self.right_loading = False # 正在读取右侧 SVN 历史

        # 左侧端点
        self.left_file = None
        self.left_meta = None
        self.left_entries: list = []
        self.left_specs: list = []
        self.left_options: list = []
        self._pending_left_path: str | None = None

        # 右侧端点
        self.right_file = None
        self.right_meta = None
        self.right_entries: list = []
        self.right_specs: list = []
        self.right_options: list = []
        self._pending_right_path: str | None = None

        self._build(parent)

    # ── 左侧加载 ──
    def on_drop_left(self, event):
        self._load_left(strip_path(event.data))

    def browse_left(self):
        path = filedialog.askopenfilename(filetypes=[("Prefab files", "*.prefab")])
        if path:
            self._load_left(path)

    def _load_left(self, path: str):
        if not self._validate(path):
            return
        self._pending_left_path = path
        self._show_left_loading()
        self.left_loading = True
        self._refresh_controls()
        threading.Thread(target=self._load_left_worker, args=(path,), daemon=True).start()

    def _load_left_worker(self, path: str):
        try:
            meta = svnh.info(path)
            entries = svnh.log(path)
            info = _parse_info(path)
            self.shell.root.after(0, self._on_left_loaded, path, meta, entries, info)
        except Exception as e:
            self.shell.root.after(0, self._on_left_failed, path, str(e))

    def _on_left_loaded(self, path: str, meta: dict, entries: list, info: dict):
        if self._pending_left_path != path:
            return  # 加载过程中已被清除/覆盖，忽略过期回调
        self._pending_left_path = None
        self.left_loading = False

        self.left_file = path
        self.left_meta = meta
        self.left_entries = entries
        self.left_specs = [_WORKING] + [("rev", e["rev"]) for e in entries]
        self.left_options = ["工作副本（含未提交改动）"] + [
            f"r{e['rev']}  {e['date']}  {e['msg'][:30]}" for e in entries
        ]
        self.left_cb.config(values=self.left_options)
        self.left_cb.current(1 if len(self.left_options) > 1 else 0)
        self._update_left_ui(info)
        self._update_meta_labels()
        self._refresh_controls()
        self._check_ready()

    def _on_left_failed(self, path: str, error: str):
        if self._pending_left_path != path:
            return
        self._pending_left_path = None
        self.left_loading = False
        self._clear_left()
        self.shell.set_status("❌ 左侧文件加载失败")
        messagebox.showerror("加载失败", error)

    def _clear_left(self):
        self._pending_left_path = None
        self.left_loading = False
        self.left_file = None
        self.left_meta = None
        self.left_entries = []
        self.left_specs = []
        self.left_options = []
        self.left_cb.config(values=[])
        self._update_left_ui()
        self._update_meta_labels()
        self._refresh_controls()
        self._check_ready()

    # ── 右侧加载 ──
    def on_drop_right(self, event):
        self._load_right(strip_path(event.data))

    def browse_right(self):
        path = filedialog.askopenfilename(filetypes=[("Prefab files", "*.prefab")])
        if path:
            self._load_right(path)

    def _load_right(self, path: str):
        if not self._validate(path):
            return
        self._pending_right_path = path
        self._show_right_loading()
        self.right_loading = True
        self._refresh_controls()
        threading.Thread(target=self._load_right_worker, args=(path,), daemon=True).start()

    def _load_right_worker(self, path: str):
        try:
            meta = svnh.info(path)
            entries = svnh.log(path)
            info = _parse_info(path)
            self.shell.root.after(0, self._on_right_loaded, path, meta, entries, info)
        except Exception as e:
            self.shell.root.after(0, self._on_right_failed, path, str(e))

    def _on_right_loaded(self, path: str, meta: dict, entries: list, info: dict):
        if self._pending_right_path != path:
            return
        self._pending_right_path = None
        self.right_loading = False

        self.right_file = path
        self.right_meta = meta
        self.right_entries = entries
        self.right_specs = [_WORKING] + [("rev", e["rev"]) for e in entries]
        self.right_options = ["工作副本（含未提交改动）"] + [
            f"r{e['rev']}  {e['date']}  {e['msg'][:30]}" for e in entries
        ]
        self.right_cb.config(values=self.right_options)
        self.right_cb.current(1 if len(self.right_options) > 1 else 0)
        self._update_right_ui(info)
        self._update_meta_labels()
        self._refresh_controls()
        self._check_ready()

    def _on_right_failed(self, path: str, error: str):
        if self._pending_right_path != path:
            return
        self._pending_right_path = None
        self.right_loading = False
        self._clear_right()
        self.shell.set_status("❌ 右侧文件加载失败")
        messagebox.showerror("加载失败", error)

    def _clear_right(self):
        self._pending_right_path = None
        self.right_loading = False
        self.right_file = None
        self.right_meta = None
        self.right_entries = []
        self.right_specs = []
        self.right_options = []
        self.right_cb.config(values=[])
        self._update_right_ui()
        self._update_meta_labels()
        self._refresh_controls()
        self._check_ready()

    # ── 公共辅助 ──
    def _validate(self, path: str) -> bool:
        if not path.lower().endswith(".prefab"):
            messagebox.showwarning("格式错误", f"请选择 .prefab 文件\n当前: {path}")
            return False
        if not svnh.svn_available():
            messagebox.showerror("缺少 svn", "未找到 svn 命令，请先安装 SVN 命令行客户端并加入 PATH")
            return False
        return True

    def _show_left_loading(self):
        self.left_drop_frame.pack_forget()
        self.left_info_frame.pack(fill="both", expand=True, padx=8, pady=8)
        self.left_name_lbl.config(text="⏳ 正在读取 SVN 历史...", fg=ACCENT)
        self.left_url_lbl.config(text="")
        self.left_node_lbl.config(text="")
        self.left_cb.config(values=[])
        self.left_meta_lbl.config(text="")

    def _show_right_loading(self):
        self.right_drop_frame.pack_forget()
        self.right_info_frame.pack(fill="both", expand=True, padx=8, pady=8)
        self.right_name_lbl.config(text="⏳ 正在读取 SVN 历史...", fg=ACCENT)
        self.right_url_lbl.config(text="")
        self.right_node_lbl.config(text="")
        self.right_cb.config(values=[])
        self.right_meta_lbl.config(text="")

    def _update_left_ui(self, info: dict | None = None):
        if self.left_file:
            if info is None:
                info = _parse_info(self.left_file)
            self.left_name_lbl.config(text=os.path.basename(self.left_file), fg=TEXT)
            self.left_url_lbl.config(text=f"r{self.left_meta['rev']}  ·  {self.left_meta['url']}")
            if info["ok"]:
                self.left_node_lbl.config(text=f"📄 {info['node_count']} 节点")
            else:
                self.left_node_lbl.config(text=f"⚠️ {info['error']}")
            self.left_drop_frame.pack_forget()
            self.left_info_frame.pack(fill="both", expand=True, padx=8, pady=8)
        else:
            self.left_name_lbl.config(text="", fg=TEXT)
            self.left_url_lbl.config(text="")
            self.left_node_lbl.config(text="")
            self.left_info_frame.pack_forget()
            self.left_drop_frame.pack(fill="both", expand=True, padx=8, pady=8)

    def _update_right_ui(self, info: dict | None = None):
        if self.right_file:
            if info is None:
                info = _parse_info(self.right_file)
            self.right_name_lbl.config(text=os.path.basename(self.right_file), fg=TEXT)
            self.right_url_lbl.config(text=f"r{self.right_meta['rev']}  ·  {self.right_meta['url']}")
            if info["ok"]:
                self.right_node_lbl.config(text=f"📄 {info['node_count']} 节点")
            else:
                self.right_node_lbl.config(text=f"⚠️ {info['error']}")
            self.right_drop_frame.pack_forget()
            self.right_info_frame.pack(fill="both", expand=True, padx=8, pady=8)
        else:
            self.right_name_lbl.config(text="", fg=TEXT)
            self.right_url_lbl.config(text="")
            self.right_node_lbl.config(text="")
            self.right_info_frame.pack_forget()
            self.right_drop_frame.pack(fill="both", expand=True, padx=8, pady=8)

    # ── 版本选择 ──
    def _on_version_changed(self, _event=None):
        self._update_meta_labels()
        self._check_ready()

    def _update_meta_labels(self):
        self._render_meta(self.left_cb, self.left_specs, self.left_entries, self.left_meta_lbl)
        self._render_meta(self.right_cb, self.right_specs, self.right_entries, self.right_meta_lbl)

    def _render_meta(self, cb: ttk.Combobox, specs: list, entries: list, lbl: tk.Label):
        idx = cb.current()
        if idx < 0 or idx >= len(specs):
            lbl.config(text="", fg=TEXT_DARK)
            return
        kind, rev = specs[idx]
        if kind == "working":
            lbl.config(text="当前工作副本（含未提交改动）", fg=ACCENT)
        else:
            entry = entries[idx - 1]
            msg = entry["msg"].replace("\n", " ").replace("\r", " ").strip()
            if len(msg) > 120:
                msg = msg[:120] + "..."
            lbl.config(
                text=f"{entry['date']}  ·  {entry.get('author', 'unknown')}  ·  {msg}",
                fg=TEXT_DIM,
            )

    def _swap_sides(self):
        # 加载中禁止交换
        if self.busy or self.left_loading or self.right_loading:
            return
        # 交换文件与历史记录
        self.left_file, self.right_file = self.right_file, self.left_file
        self.left_meta, self.right_meta = self.right_meta, self.left_meta
        self.left_entries, self.right_entries = self.right_entries, self.left_entries
        self.left_specs, self.right_specs = self.right_specs, self.left_specs
        self.left_options, self.right_options = self.right_options, self.left_options

        # 交换下拉框内容与当前选中项
        li, ri = self.left_cb.current(), self.right_cb.current()
        self.left_cb.config(values=self.left_options)
        self.right_cb.config(values=self.right_options)
        self.left_cb.current(ri if ri >= 0 else 0)
        self.right_cb.current(li if li >= 0 else 0)

        self._update_left_ui()
        self._update_right_ui()
        self._update_meta_labels()
        self._refresh_controls()
        self._check_ready()

    # ── 对比 ──
    def do_compare(self):
        if self.busy or self.left_loading or self.right_loading or not self.left_file or not self.right_file:
            return
        li, ri = self.left_cb.current(), self.right_cb.current()
        if li < 0 or ri < 0:
            return
        left_spec, right_spec = self.left_specs[li], self.right_specs[ri]
        if left_spec == right_spec and self.left_file == self.right_file:
            messagebox.showinfo("提示", "两个端点相同，无需对比")
            return
        self._set_controls(False)
        self.compare_btn.config(text="⏳ 正在取版本并对比...")
        threading.Thread(target=self._worker, args=(left_spec, right_spec), daemon=True).start()

    def _resolve(self, spec, file_path: str, workdir: str, side: str) -> tuple:
        """把端点解析成 (文件路径, 标签)。工作副本端直接用 WC 文件，不 cat。"""
        kind, rev = spec
        if kind == "working":
            return file_path, "working"
        dest = os.path.join(workdir, f"{side}.prefab")
        svnh.cat(file_path, rev, dest)
        return dest, f"r{rev}"

    def _worker(self, left_spec, right_spec):
        root = self.shell.root
        work = svnh.make_workdir()
        try:
            left_path, left_label = self._resolve(left_spec, self.left_file, work, "left")
            right_path, right_label = self._resolve(right_spec, self.right_file, work, "right")
            result = diff_prefabs(left_path, right_path)
            left_base = os.path.basename(self.left_file)
            right_base = os.path.basename(self.right_file)
            result.before_path = f"{left_base}@{left_label}"
            result.after_path = f"{right_base}@{right_label}"

            ensure_dir(BRANCH_REPORTS_DIR)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            name = f"{safe_name(left_base)}_{left_label}__vs__{safe_name(right_base)}_{right_label}_{stamp}"
            html = os.path.join(BRANCH_REPORTS_DIR, name + ".html")
            write_tree_report(result, html)
            write_json_report(result, os.path.join(BRANCH_REPORTS_DIR, name + ".json"))
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
        """根据当前状态刷新 combobox / 交换 / 清除 / 浏览按钮的启用状态。"""
        self.left_cb.config(
            state="readonly" if (self.left_file and not self.busy and not self.left_loading) else "disabled"
        )
        self.right_cb.config(
            state="readonly" if (self.right_file and not self.busy and not self.right_loading) else "disabled"
        )
        self.swap_btn.config(
            state="normal" if (self.left_file and self.right_file and not self.busy
                               and not self.left_loading and not self.right_loading) else "disabled"
        )
        # 加载期间禁用清除/浏览，避免触发竞态
        self.left_clear_btn.config(state="disabled" if self.left_loading else "normal")
        self.left_browse_btn.config(state="disabled" if self.left_loading else "normal")
        self.right_clear_btn.config(state="disabled" if self.right_loading else "normal")
        self.right_browse_btn.config(state="disabled" if self.right_loading else "normal")

    def _check_ready(self):
        li, ri = self.left_cb.current(), self.right_cb.current()
        same_file = self.left_file and self.right_file and self.left_file == self.right_file
        same_spec = li >= 0 and ri >= 0 and self.left_specs[li] == self.right_specs[ri]
        ready = bool(
            self.left_file and self.right_file and li >= 0 and ri >= 0
            and not (same_file and same_spec)
            and not self.busy and not self.left_loading and not self.right_loading
        )
        self.compare_btn.config(
            state="normal" if ready else "disabled",
            text="🔍 生成分支对比报告" if ready else "请先拖入两个分支的 prefab 并选择版本",
        )

    # ── 构建 ──
    def _build(self, parent: tk.Misc):
        drop_area = tk.Frame(parent, bg=BG)
        drop_area.pack(fill="both", expand=True, padx=8, pady=8)
        drop_area.grid_columnconfigure(0, weight=1, uniform="branch_cards")
        drop_area.grid_columnconfigure(1, weight=1, uniform="branch_cards")
        drop_area.grid_rowconfigure(0, weight=1)

        # ── 左侧卡片：分支 A ──
        left_card = tk.Frame(drop_area, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=2)
        left_card.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        self.left_drop_frame = tk.Frame(left_card, bg=CARD_BG)
        self.left_drop_frame.pack(fill="both", expand=True)
        self.left_drop_frame.drop_target_register(DND_FILES)
        self.left_drop_frame.dnd_bind("<<Drop>>", self.on_drop_left)

        tk.Label(self.left_drop_frame, text="🌿 分支 A（旧版本）", bg=CARD_BG, fg=TEXT_DIM,
                 font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
        tk.Label(self.left_drop_frame, text="拖入分支 A 的 .prefab", bg=CARD_BG, fg=TEXT_DIM,
                 font=(FONT_FAMILY, 11)).pack(expand=True)
        tk.Label(self.left_drop_frame, text="或点击选择文件", bg=CARD_BG, fg=TEXT_DARK,
                 font=(FONT_FAMILY, 9)).pack()
        tk.Button(self.left_drop_frame, text="📂 浏览...", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2",
                  command=self.browse_left, font=(FONT_FAMILY, 9)).pack(pady=8)

        self.left_info_frame = tk.Frame(left_card, bg=CARD_BG)
        tk.Label(self.left_info_frame, text="🌿 分支 A（旧版本）", bg=CARD_BG, fg=TEXT_DIM,
                 font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
        self.left_name_lbl = tk.Label(self.left_info_frame, text="", bg=CARD_BG, fg=TEXT,
                                      font=(FONT_FAMILY, 10, "bold"))
        self.left_name_lbl.pack(anchor="w", padx=8, pady=(4, 0))
        self.left_url_lbl = tk.Label(self.left_info_frame, text="", bg=CARD_BG, fg=TEXT_DARK,
                                     font=(FONT_FAMILY, 9), wraplength=380, justify="left")
        self.left_url_lbl.pack(fill="x", padx=8)
        self.left_node_lbl = tk.Label(self.left_info_frame, text="", bg=CARD_BG, fg=TEXT_DIM,
                                      font=(FONT_FAMILY, 9))
        self.left_node_lbl.pack(anchor="w", padx=8, pady=(2, 0))
        left_row = tk.Frame(self.left_info_frame, bg=CARD_BG)
        left_row.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(left_row, text="版本", bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 9)).pack(side="left")
        self.left_cb = ttk.Combobox(left_row, state="readonly")
        self.left_cb.pack(side="left", fill="x", expand=True, padx=8)
        self.left_cb.bind("<<ComboboxSelected>>", self._on_version_changed)
        self.left_meta_lbl = tk.Label(self.left_info_frame, text="", bg=CARD_BG, fg=TEXT_DIM,
                                      font=(FONT_FAMILY, 9), wraplength=380, justify="left")
        self.left_meta_lbl.pack(fill="x", padx=8, pady=(0, 8))
        left_btn_row = tk.Frame(self.left_info_frame, bg=CARD_BG)
        left_btn_row.pack(anchor="e", padx=8, pady=8)
        self.left_clear_btn = tk.Button(left_btn_row, text="🗑 清除", bg=CARD_BG, fg=TEXT_DIM, bd=0,
                                        cursor="hand2", command=self._clear_left, font=(FONT_FAMILY, 9))
        self.left_clear_btn.pack(side="right", padx=4)
        self.left_browse_btn = tk.Button(left_btn_row, text="📂 浏览...", bg=CARD_BG, fg=ACCENT, bd=0,
                                         cursor="hand2", command=self.browse_left, font=(FONT_FAMILY, 9))
        self.left_browse_btn.pack(side="right", padx=4)

        # ── 右侧卡片：分支 B ──
        right_card = tk.Frame(drop_area, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=2)
        right_card.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)

        self.right_drop_frame = tk.Frame(right_card, bg=CARD_BG)
        self.right_drop_frame.pack(fill="both", expand=True)
        self.right_drop_frame.drop_target_register(DND_FILES)
        self.right_drop_frame.dnd_bind("<<Drop>>", self.on_drop_right)

        tk.Label(self.right_drop_frame, text="🌿 分支 B（新版本）", bg=CARD_BG, fg=TEXT_DIM,
                 font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
        tk.Label(self.right_drop_frame, text="拖入分支 B 的 .prefab", bg=CARD_BG, fg=TEXT_DIM,
                 font=(FONT_FAMILY, 11)).pack(expand=True)
        tk.Label(self.right_drop_frame, text="或点击选择文件", bg=CARD_BG, fg=TEXT_DARK,
                 font=(FONT_FAMILY, 9)).pack()
        tk.Button(self.right_drop_frame, text="📂 浏览...", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2",
                  command=self.browse_right, font=(FONT_FAMILY, 9)).pack(pady=8)

        self.right_info_frame = tk.Frame(right_card, bg=CARD_BG)
        tk.Label(self.right_info_frame, text="🌿 分支 B（新版本）", bg=CARD_BG, fg=TEXT_DIM,
                 font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
        self.right_name_lbl = tk.Label(self.right_info_frame, text="", bg=CARD_BG, fg=TEXT,
                                       font=(FONT_FAMILY, 10, "bold"))
        self.right_name_lbl.pack(anchor="w", padx=8, pady=(4, 0))
        self.right_url_lbl = tk.Label(self.right_info_frame, text="", bg=CARD_BG, fg=TEXT_DARK,
                                      font=(FONT_FAMILY, 9), wraplength=380, justify="left")
        self.right_url_lbl.pack(fill="x", padx=8)
        self.right_node_lbl = tk.Label(self.right_info_frame, text="", bg=CARD_BG, fg=TEXT_DIM,
                                       font=(FONT_FAMILY, 9))
        self.right_node_lbl.pack(anchor="w", padx=8, pady=(2, 0))
        right_row = tk.Frame(self.right_info_frame, bg=CARD_BG)
        right_row.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(right_row, text="版本", bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 9)).pack(side="left")
        self.right_cb = ttk.Combobox(right_row, state="readonly")
        self.right_cb.pack(side="left", fill="x", expand=True, padx=8)
        self.right_cb.bind("<<ComboboxSelected>>", self._on_version_changed)
        self.right_meta_lbl = tk.Label(self.right_info_frame, text="", bg=CARD_BG, fg=TEXT_DIM,
                                       font=(FONT_FAMILY, 9), wraplength=380, justify="left")
        self.right_meta_lbl.pack(fill="x", padx=8, pady=(0, 8))
        right_btn_row = tk.Frame(self.right_info_frame, bg=CARD_BG)
        right_btn_row.pack(anchor="e", padx=8, pady=8)
        self.right_clear_btn = tk.Button(right_btn_row, text="🗑 清除", bg=CARD_BG, fg=TEXT_DIM, bd=0,
                                         cursor="hand2", command=self._clear_right, font=(FONT_FAMILY, 9))
        self.right_clear_btn.pack(side="right", padx=4)
        self.right_browse_btn = tk.Button(right_btn_row, text="📂 浏览...", bg=CARD_BG, fg=ACCENT, bd=0,
                                          cursor="hand2", command=self.browse_right, font=(FONT_FAMILY, 9))
        self.right_browse_btn.pack(side="right", padx=4)

        # 操作按钮
        action_bar = tk.Frame(parent, bg=BG)
        action_bar.pack(fill="x", padx=16, pady=8)
        self.compare_btn = tk.Button(action_bar, text="请先拖入两个分支的 prefab 并选择版本", bg=BORDER,
                                     fg=TEXT_DIM, bd=0, padx=20, pady=6, cursor="hand2", state="disabled",
                                     command=self.do_compare, font=(FONT_FAMILY, 10, "bold"))
        self.compare_btn.pack(side="left")
        self.swap_btn = tk.Button(action_bar, text="🔃 交换", bg=CARD_BG, fg=ACCENT, bd=0,
                                  padx=14, pady=6, cursor="hand2", state="disabled",
                                  command=self._swap_sides, font=(FONT_FAMILY, 10, "bold"))
        self.swap_btn.pack(side="left", padx=8)
        self.view_btn = tk.Button(action_bar, text="👁 查看报告", bg=PRIMARY_BTN_BG, fg=TEXT, bd=0,
                                  padx=16, pady=6, cursor="hand2", state="disabled",
                                  font=(FONT_FAMILY, 10, "bold"))
        self.view_btn.pack(side="left", padx=8)
