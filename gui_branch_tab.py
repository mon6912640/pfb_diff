#!/usr/bin/env python3
"""PfbDiff GUI — 「🌿 分支对比」页签（同一文件在不同分支上的版本）。

拖入 SVN 工作副本内的 .prefab（= 你当前分支的版本），再指定对面分支上同一
文件的 URL，对比两者。对面 URL 以「用户给/确认的完整 URL」为准——自动列举
分支只是便利（仓库布局不统一时仍可手动粘贴），与具体布局无关、永远可用。

取数走 svn_revision_helper（后台线程），对比与报告复用 diff_engine /
report_html_tree，UI 框架复用 AppShell。
"""

import os
import shutil
import threading
import time

import tkinter as tk
from tkinter import filedialog, messagebox

from tkinterdnd2 import DND_FILES

import svn_revision_helper as svnh
from diff_engine import diff_prefabs
from report_html_tree import write_html_report as write_tree_report
from report_json import write_json_report

from gui_shell import AppShell, BRANCH_REPORTS_DIR, ensure_dir, safe_name, strip_path
from gui_theme import (
    BG, CARD_BG, BORDER, TEXT, TEXT_DIM, TEXT_DARK, ACCENT, PRIMARY_BTN_BG, FONT_FAMILY,
)


class BranchTab:
    def __init__(self, shell: AppShell, parent: tk.Misc):
        self.shell = shell
        self.file = None       # 当前分支（工作副本）里的文件
        self.meta = None       # svn info 结果
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
            self.meta = svnh.info(path)
        except svnh.SvnError as e:
            messagebox.showerror("无法读取 svn 信息", f"{e}\n\n该文件需位于 SVN 工作副本内。")
            return

        self.file = path
        self.info_lbl.config(text=f"当前：{os.path.basename(path)} @ r{self.meta['rev']}  ·  {self.meta['url']}")
        # 目标 URL 预填当前文件 URL，供用户改成对面分支
        self.target_var.set(self.meta["url"])
        self.drop_frame.pack_forget()
        self.body_frame.pack(fill="x", padx=8, pady=8)
        self.compare_btn.config(state="normal")

    # ── 列分支（便利，失败不致命）──
    def list_branches(self):
        if not self.meta:
            return
        names = svnh.list_branches(self.meta["repo_root"])
        if not names:
            messagebox.showinfo("未发现标准 branches",
                                "未在仓库根下发现 branches 目录。\n请直接把对面分支上该文件的完整 URL 粘到目标框。")
            return
        self._open_branch_chooser(names)

    def _apply_branch(self, name: str):
        """best-effort：把当前文件的「分支内路径」拼到 branches/<name>/ 下，填入目标框。

        用户可在目标框里继续修正——最终以框里的 URL 为准。
        """
        rel = self.meta["rel_path"]              # 如 trunk/Assets/foo.prefab 或 branches/x/Assets/foo.prefab
        parts = rel.split("/")
        if parts and parts[0] == "branches" and len(parts) >= 2:
            inbranch = "/".join(parts[2:])       # 去掉 branches/<旧分支>
        elif parts and parts[0] == "trunk":
            inbranch = "/".join(parts[1:])        # 去掉 trunk
        else:
            inbranch = rel                        # 非标准布局：原样拼，交给用户改
        target = self.meta["repo_root"].rstrip("/") + "/branches/" + name + "/" + inbranch
        self.target_var.set(target)

    def _open_branch_chooser(self, names):
        top = tk.Toplevel(self.shell.root, bg=CARD_BG)
        top.title("选择目标分支")
        top.geometry("360x320")
        tk.Label(top, text="双击选择分支（之后可在目标框微调）", bg=CARD_BG, fg=TEXT_DIM,
                 font=(FONT_FAMILY, 9)).pack(anchor="w", padx=8, pady=6)
        lb = tk.Listbox(top, bg=BG, fg=TEXT, highlightthickness=0, bd=0)
        for n in names:
            lb.insert("end", n)
        lb.pack(fill="both", expand=True, padx=8, pady=8)

        def _pick(_event=None):
            sel = lb.curselection()
            if sel:
                self._apply_branch(names[sel[0]])
                top.destroy()

        lb.bind("<Double-Button-1>", _pick)
        tk.Button(top, text="选择", bg=PRIMARY_BTN_BG, fg=TEXT, bd=0, padx=14, pady=4,
                  cursor="hand2", command=_pick, font=(FONT_FAMILY, 9, "bold")).pack(pady=(0, 8))

    # ── 对比 ──
    def do_compare(self):
        if self.busy or not self.file:
            return
        target = self.target_var.get().strip()
        if not target:
            messagebox.showinfo("提示", "请填写对面分支上该文件的 URL")
            return
        rev = (self.rev_var.get().strip() or "HEAD")
        self.busy = True
        self.compare_btn.config(state="disabled", text="⏳ 正在取分支版本并对比...")
        threading.Thread(target=self._worker, args=(target, rev), daemon=True).start()

    def _worker(self, target_url: str, rev: str):
        root = self.shell.root
        work = svnh.make_workdir()
        try:
            # 左 = 当前工作副本文件本身；右 = 目标分支 URL @ rev
            right = svnh.cat(target_url, rev, os.path.join(work, "right.prefab"))
            result = diff_prefabs(self.file, right)
            base = os.path.basename(self.file)
            result.before_path = f"{base}@工作副本"
            result.after_path = f"{target_url}@{rev}"

            ensure_dir(BRANCH_REPORTS_DIR)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            name = f"{safe_name(base)}_branch_{stamp}"
            html = os.path.join(BRANCH_REPORTS_DIR, name + ".html")
            write_tree_report(result, html)
            write_json_report(result, os.path.join(BRANCH_REPORTS_DIR, name + ".json"))
            root.after(0, self._on_done, html)
        except Exception as e:
            root.after(0, self._on_fail, str(e))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _on_done(self, html: str):
        self.busy = False
        self.compare_btn.config(state="normal", text="🔍 生成分支对比报告")
        self.shell.set_status(f"✅ 已完成: {os.path.basename(html)}")
        self.view_btn.config(state="normal", command=lambda: self.shell.open_report(html))
        self.shell.load_recent_reports()
        self.shell.open_report(html)

    def _on_fail(self, error: str):
        self.busy = False
        self.compare_btn.config(state="normal", text="🔍 生成分支对比报告")
        self.shell.set_status("❌ 对比失败")
        messagebox.showerror("对比失败", error)

    # ── 构建 ──
    def _build(self, parent: tk.Misc):
        self.target_var = tk.StringVar()
        self.rev_var = tk.StringVar(value="HEAD")

        card = tk.Frame(parent, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=2)
        card.pack(fill="x", padx=16, pady=(16, 8))

        # 未加载文件时的拖放区
        self.drop_frame = tk.Frame(card, bg=CARD_BG)
        self.drop_frame.pack(fill="both", expand=True)
        self.drop_frame.drop_target_register(DND_FILES)
        self.drop_frame.dnd_bind("<<Drop>>", self.on_drop)
        tk.Label(self.drop_frame, text="🌿 拖入 SVN 工作副本内的 .prefab（你当前分支的版本）",
                 bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 11)).pack(pady=(16, 0))
        tk.Label(self.drop_frame, text="再指定对面分支上同一文件的 URL 进行对比",
                 bg=CARD_BG, fg=TEXT_DARK, font=(FONT_FAMILY, 9)).pack()
        tk.Button(self.drop_frame, text="📂 选择文件", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2",
                  command=self.browse, font=(FONT_FAMILY, 9)).pack(pady=(4, 16))

        # 加载后的目标设置区
        self.body_frame = tk.Frame(card, bg=CARD_BG)
        self.info_lbl = tk.Label(self.body_frame, text="", bg=CARD_BG, fg=TEXT, font=(FONT_FAMILY, 9, "bold"))
        self.info_lbl.pack(anchor="w", padx=8, pady=(8, 6))

        trow = tk.Frame(self.body_frame, bg=CARD_BG)
        trow.pack(fill="x", padx=8, pady=(0, 4))
        tk.Label(trow, text="对面 URL", bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 9)).pack(side="left")
        tk.Entry(trow, textvariable=self.target_var, bg=BG, fg=TEXT, insertbackground=TEXT,
                 relief="flat", font=(FONT_FAMILY, 9)).pack(side="left", fill="x", expand=True, padx=8)
        tk.Button(trow, text="📋 列出分支", bg=CARD_BG, fg=ACCENT, bd=0, cursor="hand2",
                  command=self.list_branches, font=(FONT_FAMILY, 9)).pack(side="left")

        rrow = tk.Frame(self.body_frame, bg=CARD_BG)
        rrow.pack(fill="x", padx=8, pady=(0, 8))
        tk.Label(rrow, text="对面版本", bg=CARD_BG, fg=TEXT_DIM, font=(FONT_FAMILY, 9)).pack(side="left")
        tk.Entry(rrow, textvariable=self.rev_var, bg=BG, fg=TEXT, insertbackground=TEXT,
                 relief="flat", width=12, font=(FONT_FAMILY, 9)).pack(side="left", padx=8)
        tk.Label(rrow, text="（默认 HEAD，可填具体 revision）", bg=CARD_BG, fg=TEXT_DARK,
                 font=(FONT_FAMILY, 9)).pack(side="left")

        tk.Button(self.body_frame, text="🔄 换个文件", bg=CARD_BG, fg=TEXT_DIM, bd=0, cursor="hand2",
                  command=self.browse, font=(FONT_FAMILY, 9)).pack(anchor="e", padx=8, pady=(0, 8))

        # 操作按钮
        action = tk.Frame(parent, bg=BG)
        action.pack(fill="x", padx=16, pady=8)
        self.compare_btn = tk.Button(action, text="🔍 生成分支对比报告", bg=PRIMARY_BTN_BG, fg=TEXT, bd=0,
                                     padx=20, pady=6, cursor="hand2", state="disabled",
                                     command=self.do_compare, font=(FONT_FAMILY, 10, "bold"))
        self.compare_btn.pack(side="left")
        self.view_btn = tk.Button(action, text="👁 查看报告", bg=PRIMARY_BTN_BG, fg=TEXT, bd=0,
                                  padx=16, pady=6, cursor="hand2", state="disabled",
                                  font=(FONT_FAMILY, 10, "bold"))
        self.view_btn.pack(side="left", padx=8)
