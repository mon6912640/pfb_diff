#!/usr/bin/env python3
"""PfbDiff GUI — 「📊 两方对比」页签。

拖入任意两个 .prefab，生成树形对比报告。所有 before/after 状态与控件
都封装在 CompareTab 实例里，不再使用模块级全局。
"""

import os

import tkinter as tk
from tkinter import filedialog, messagebox

from tkinterdnd2 import DND_FILES

from diff_engine import diff_prefabs
from report_html_tree import write_html_report as write_tree_report
from report_json import write_json_report
from prefab_parser import parse_prefab

from gui_shell import AppShell, default_report_paths, strip_path
from gui_theme import (
    BG, CARD_BG, BORDER, TEXT, TEXT_DIM, TEXT_DARK, ACCENT, PRIMARY_BTN_BG, FONT_FAMILY,
)


class CompareState:
    def __init__(self):
        self.before_file: str | None = None
        self.after_file: str | None = None
        self.before_name: str = ""
        self.after_name: str = ""
        self.before_path: str = ""
        self.after_path: str = ""


def _parse_info(file_path: str) -> dict:
    try:
        doc = parse_prefab(file_path)
        return {"ok": True, "node_count": len(doc.nodes)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class CompareTab:
    """两方对比页签：自带状态与控件，依赖 AppShell 提供状态栏/最近报告/打开报告。"""

    def __init__(self, shell: AppShell, parent: tk.Misc):
        self.shell = shell
        self.state = CompareState()
        self._build(parent)

    # ── 拖放 / 选择 ──
    def on_drop_before(self, event):
        path = strip_path(event.data)
        if not path.lower().endswith(".prefab"):
            messagebox.showwarning("格式错误", f"请选择 .prefab 文件\n当前: {path}")
            return
        self._set_before(path)

    def on_drop_after(self, event):
        path = strip_path(event.data)
        if not path.lower().endswith(".prefab"):
            messagebox.showwarning("格式错误", f"请选择 .prefab 文件\n当前: {path}")
            return
        self._set_after(path)

    def browse_before(self):
        path = filedialog.askopenfilename(filetypes=[("Prefab files", "*.prefab")])
        if path:
            self._set_before(path)

    def browse_after(self):
        path = filedialog.askopenfilename(filetypes=[("Prefab files", "*.prefab")])
        if path:
            self._set_after(path)

    def remove_before(self):
        self.state.before_file = None
        self.state.before_name = ""
        self.state.before_path = ""
        self.update_before_ui()

    def remove_after(self):
        self.state.after_file = None
        self.state.after_name = ""
        self.state.after_path = ""
        self.update_after_ui()

    def _set_before(self, path: str):
        self.state.before_file = path
        self.state.before_name = os.path.basename(path)
        self.state.before_path = path
        self.update_before_ui()

    def _set_after(self, path: str):
        self.state.after_file = path
        self.state.after_name = os.path.basename(path)
        self.state.after_path = path
        self.update_after_ui()

    # ── UI 刷新 ──
    def update_before_ui(self):
        if self.state.before_file:
            info = _parse_info(self.state.before_file)
            self.before_name_lbl.config(text=self.state.before_name)
            if info["ok"]:
                self.before_meta_lbl.config(text=f"📄 {info['node_count']} 节点")
            else:
                self.before_meta_lbl.config(text=f"⚠️ {info['error']}")
            self.before_path_lbl.config(text=self.state.before_path)
            self.before_drop_frame.pack_forget()
            self.before_info_frame.pack(fill="both", expand=True, padx=8, pady=8)
        else:
            self.before_name_lbl.config(text="")
            self.before_meta_lbl.config(text="")
            self.before_path_lbl.config(text="")
            self.before_info_frame.pack_forget()
            self.before_drop_frame.pack(fill="both", expand=True, padx=8, pady=8)
        self.check_ready()

    def update_after_ui(self):
        if self.state.after_file:
            info = _parse_info(self.state.after_file)
            self.after_name_lbl.config(text=self.state.after_name)
            if info["ok"]:
                self.after_meta_lbl.config(text=f"📄 {info['node_count']} 节点")
            else:
                self.after_meta_lbl.config(text=f"⚠️ {info['error']}")
            self.after_path_lbl.config(text=self.state.after_path)
            self.after_drop_frame.pack_forget()
            self.after_info_frame.pack(fill="both", expand=True, padx=8, pady=8)
        else:
            self.after_name_lbl.config(text="")
            self.after_meta_lbl.config(text="")
            self.after_path_lbl.config(text="")
            self.after_info_frame.pack_forget()
            self.after_drop_frame.pack(fill="both", expand=True, padx=8, pady=8)
        self.check_ready()

    def check_ready(self):
        ready = bool(self.state.before_file and self.state.after_file)
        self.gen_btn.config(
            state="normal" if ready else "disabled",
            text="🔍 生成对比报告" if ready else "请先拖入两个 prefab",
        )

    # ── 生成报告 ──
    def do_generate(self):
        if not self.state.before_file or not self.state.after_file:
            messagebox.showwarning("提示", "请先选择两个 prefab 文件")
            return
        self.gen_btn.config(state="disabled", text="⏳ 正在生成...")
        self.shell.root.update()

        try:
            result = diff_prefabs(self.state.before_file, self.state.after_file)
            if self.state.before_path:
                result.before_path = self.state.before_path
            if self.state.after_path:
                result.after_path = self.state.after_path
            paths = default_report_paths(self.state.before_name, self.state.after_name)
            write_tree_report(result, paths["html"])
            write_json_report(result, paths["json"])

            self.shell.set_status(f"✅ 已完成: {os.path.basename(paths['html'])}")
            self.view_btn.config(state="normal", command=lambda: self.shell.open_report(paths["html"]))
            self.shell.load_recent_reports()
            messagebox.showinfo("完成", "报告生成成功")
        except Exception as e:
            messagebox.showerror("失败", f"生成失败: {e}")
            self.shell.set_status("❌ 生成失败")
        finally:
            self.check_ready()

    # ── 构建 ──
    def _build(self, parent: tk.Misc):
        drop_area = tk.Frame(parent, bg=BG)
        drop_area.pack(fill="both", expand=True, padx=8, pady=8)
        drop_area.grid_columnconfigure(0, weight=1)
        drop_area.grid_columnconfigure(1, weight=1)
        drop_area.grid_rowconfigure(0, weight=1)

        # ── Before 卡片 ──
        before_card = tk.Frame(drop_area, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=2)
        before_card.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        self.before_drop_frame = tk.Frame(before_card, bg=CARD_BG)
        self.before_drop_frame.pack(fill="both", expand=True)
        self.before_drop_frame.drop_target_register(DND_FILES)
        self.before_drop_frame.dnd_bind("<<Drop>>", self.on_drop_before)

        tk.Label(self.before_drop_frame, text="⬅ Before（旧版本）", bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
        tk.Label(self.before_drop_frame, text="拖入旧版本 .prefab", bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 11)).pack(expand=True)
        tk.Label(self.before_drop_frame, text="或点击选择文件", bg=CARD_BG, fg=TEXT_DARK, font=(FONT_FAMILY, 9)).pack()
        tk.Button(self.before_drop_frame, text="📂 浏览...", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2", command=self.browse_before, font=(FONT_FAMILY, 9)).pack(pady=8)

        self.before_info_frame = tk.Frame(before_card, bg=CARD_BG)
        tk.Label(self.before_info_frame, text="⬅ Before（旧版本）", bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
        self.before_name_lbl = tk.Label(self.before_info_frame, text="", bg=CARD_BG, fg=TEXT, font=(FONT_FAMILY, 10, "bold"))
        self.before_name_lbl.pack(anchor="w", padx=8, pady=(4, 0))
        self.before_meta_lbl = tk.Label(self.before_info_frame, text="", bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 9))
        self.before_meta_lbl.pack(anchor="w", padx=8)
        self.before_path_lbl = tk.Label(self.before_info_frame, text="", bg=CARD_BG, fg=TEXT_DARK, font=(FONT_FAMILY, 9))
        self.before_path_lbl.pack(anchor="w", padx=8, pady=(2, 0))
        btn_row = tk.Frame(self.before_info_frame, bg=CARD_BG)
        btn_row.pack(anchor="e", padx=8, pady=8)
        tk.Button(btn_row, text="🗑 移除", bg=CARD_BG, fg=TEXT_DIM, bd=0, cursor="hand2", command=self.remove_before, font=(FONT_FAMILY, 9)).pack(side="right", padx=4)
        tk.Button(btn_row, text="📂 浏览...", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2", command=self.browse_before, font=(FONT_FAMILY, 9)).pack(side="right", padx=4)

        # ── After 卡片 ──
        after_card = tk.Frame(drop_area, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=2)
        after_card.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)

        self.after_drop_frame = tk.Frame(after_card, bg=CARD_BG)
        self.after_drop_frame.pack(fill="both", expand=True)
        self.after_drop_frame.drop_target_register(DND_FILES)
        self.after_drop_frame.dnd_bind("<<Drop>>", self.on_drop_after)

        tk.Label(self.after_drop_frame, text="➡ After（新版本）", bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
        tk.Label(self.after_drop_frame, text="拖入新版本 .prefab", bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 11)).pack(expand=True)
        tk.Label(self.after_drop_frame, text="或点击选择文件", bg=CARD_BG, fg=TEXT_DARK, font=(FONT_FAMILY, 9)).pack()
        tk.Button(self.after_drop_frame, text="📂 浏览...", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2", command=self.browse_after, font=(FONT_FAMILY, 9)).pack(pady=8)

        self.after_info_frame = tk.Frame(after_card, bg=CARD_BG)
        tk.Label(self.after_info_frame, text="➡ After（新版本）", bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
        self.after_name_lbl = tk.Label(self.after_info_frame, text="", bg=CARD_BG, fg=TEXT, font=(FONT_FAMILY, 10, "bold"))
        self.after_name_lbl.pack(anchor="w", padx=8, pady=(4, 0))
        self.after_meta_lbl = tk.Label(self.after_info_frame, text="", bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 9))
        self.after_meta_lbl.pack(anchor="w", padx=8)
        self.after_path_lbl = tk.Label(self.after_info_frame, text="", bg=CARD_BG, fg=TEXT_DARK, font=(FONT_FAMILY, 9))
        self.after_path_lbl.pack(anchor="w", padx=8, pady=(2, 0))
        btn_row2 = tk.Frame(self.after_info_frame, bg=CARD_BG)
        btn_row2.pack(anchor="e", padx=8, pady=8)
        tk.Button(btn_row2, text="🗑 移除", bg=CARD_BG, fg=TEXT_DIM, bd=0, cursor="hand2", command=self.remove_after, font=(FONT_FAMILY, 9)).pack(side="right", padx=4)
        tk.Button(btn_row2, text="📂 浏览...", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2", command=self.browse_after, font=(FONT_FAMILY, 9)).pack(side="right", padx=4)

        # 操作按钮
        action_bar = tk.Frame(parent, bg=BG)
        action_bar.pack(fill="x", padx=16, pady=8)
        self.gen_btn = tk.Button(action_bar, text="请先拖入两个 prefab", bg=BORDER, fg=TEXT_DIM, bd=0, padx=20, pady=6, cursor="hand2", state="disabled", command=self.do_generate, font=(FONT_FAMILY, 10, "bold"))
        self.gen_btn.pack(side="left")
        self.view_btn = tk.Button(action_bar, text="👁 查看树形报告", bg=PRIMARY_BTN_BG, fg=TEXT, bd=0, padx=16, pady=6, cursor="hand2", state="disabled", font=(FONT_FAMILY, 10, "bold"))
        self.view_btn.pack(side="left", padx=8)
