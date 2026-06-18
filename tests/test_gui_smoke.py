#!/usr/bin/env python3
"""无头 GUI 冒烟自检 —— 重构 gui.py 的自动安全网。

不弹窗、不进 mainloop，构建完整窗口并直接驱动各回调，验证「接线」正确：
任何 widget 引用没接上、回调失联、全局漏迁，都会在这里立刻 NameError /
AttributeError 暴露，而不必手动开窗口逐个点。

覆盖范围：
  - build_app() 能无头构建（两个页签 + 框架级控件）
  - 两方对比：拖放回调更新状态、按钮启用、do_generate 真跑引擎并写报告
  - 移除文件回退到拖放区
  - SVN 冲突：定位冲突组、列表渲染、后台分析全流程（同步驱动线程回调）
  - 切页签 → 最近报告目录切换

注意：本测试有意复刻 build_app 之外、回调内部依赖的运行时状态，
重构搬动控件/全局时若行为不变则此处应保持全绿。
"""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
TEST_SVN = os.path.join(ROOT, "testSvn")

import gui
import gui_shell
import gui_compare_tab
import gui_conflict_tab
import gui_revision_tab
import svn_revision_helper as svnh

# 弹窗发生在各页签模块里，需在这些模块上 stub messagebox
_BOX_MODULES = (gui_compare_tab, gui_conflict_tab, gui_revision_tab)


class _DropEvent:
    """伪造 tkinterdnd2 的 <<Drop>> 事件：只需 .data 字段。"""

    def __init__(self, path):
        self.data = path


def _drain(root):
    """同步泵一次事件队列，让 root.after(0, ...) 排入的回调立即执行。

    冲突分析在后台线程里通过 root.after(0, ...) marshal UI 更新，
    无 mainloop 时必须手动 update 才会被处理。"""
    for _ in range(10):
        root.update()


def _wait_until(root, predicate, timeout=60.0):
    """跑真实 mainloop 直到 predicate() 为真或超时，返回是否满足。

    必须用 mainloop 而非 update()：Tkinter 非线程安全，后台线程调用
    root.after(...) 时 _tkinter 会阻塞等待主线程进入 mainloop；只 update()
    无法解锁该等待，worker 线程会永久卡住。这里用周期性 after 轮询条件，
    满足或超时即 quit() 退出 mainloop。"""
    result = {"ok": False}
    start = time.time()

    def _check():
        if predicate():
            result["ok"] = True
            root.quit()
        elif time.time() - start > timeout:
            root.quit()
        else:
            root.after(50, _check)

    root.after(50, _check)
    root.mainloop()
    return result["ok"]


class _GuiTestBase(unittest.TestCase):
    """公共 setUp/tearDown：stub 弹窗、无头建窗、收尾后台线程、取消挂起 after。"""

    def setUp(self):
        # messagebox.* 是阻塞式模态弹窗，无头测试若真弹出会一直等人点 OK。
        # 各页签模块各自 import 了 messagebox，需逐个 stub，让回调提示全部静默。
        self._orig_box = []
        for mod in _BOX_MODULES:
            for name in ("showinfo", "showwarning", "showerror"):
                self._orig_box.append((mod, name, getattr(mod.messagebox, name)))
                setattr(mod.messagebox, name, lambda *a, **k: None)

        # 每个用例独立构建一次窗口（shell 在 build_app 内创建）
        self.root = gui.build_app()
        self.root.withdraw()
        # 拦截开浏览器副作用：shell 是新实例，覆盖其方法即可，无需还原
        gui.shell.open_report = lambda p: None

    def tearDown(self):
        # 等后台分析线程收尾，避免它的 root.after 回调打到已销毁的窗口
        _wait_until(self.root, lambda: not gui.conflict_tab.busy, timeout=30.0)
        for mod, name, fn in self._orig_box:
            setattr(mod.messagebox, name, fn)
        # 取消挂起的 after/after_idle 回调，否则窗口销毁后它们打空
        # 会向 stderr 刷 "invalid command name ... (after script)" 噪音
        try:
            for aid in self.root.tk.call("after", "info"):
                try:
                    self.root.after_cancel(aid)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


class GuiSmokeTest(_GuiTestBase):
    # ── 框架 ──
    def test_build_app_constructs_tabs(self):
        # build_app 跑通即说明各页签 + 框架控件全部接线成功
        self.assertEqual(len(gui.notebook.tabs()), 3)
        self.assertIsNotNone(gui.compare_tab.gen_btn)
        self.assertIsNotNone(gui.conflict_tab.analyze_all_btn)
        self.assertIsNotNone(gui.revision_tab.compare_btn)

    # ── 两方对比 ──
    def test_drop_enables_generate_and_writes_report(self):
        tab = gui.compare_tab
        tab.on_drop_before(_DropEvent(os.path.join(FIXTURES, "comprehensive_before.prefab")))
        tab.on_drop_after(_DropEvent(os.path.join(FIXTURES, "comprehensive_after.prefab")))
        self.assertEqual(tab.gen_btn["state"], "normal")

        before = _count_html(gui_shell.COMPARE_REPORTS_DIR)
        tab.do_generate()
        after = _count_html(gui_shell.COMPARE_REPORTS_DIR)
        self.assertEqual(after, before + 1, "do_generate 应写出一份 html 报告")

    def test_remove_reverts_to_dropzone(self):
        tab = gui.compare_tab
        tab.on_drop_before(_DropEvent(os.path.join(FIXTURES, "comprehensive_before.prefab")))
        self.assertEqual(tab.gen_btn["state"], "normal" if tab.state.after_file else "disabled")
        tab.remove_before()
        self.assertIsNone(tab.state.before_file)
        self.assertEqual(tab.gen_btn["state"], "disabled")

    def test_non_prefab_drop_is_rejected(self):
        tab = gui.compare_tab
        tab.on_drop_before(_DropEvent(os.path.join(FIXTURES, "does_not_exist.txt")))
        self.assertIsNone(tab.state.before_file)

    # ── SVN 冲突分析 ──
    def test_conflict_dir_scan_populates_rows(self):
        gui.conflict_tab.on_drop(_DropEvent(TEST_SVN))
        self.assertTrue(len(gui.conflict_tab.rows) >= 1, "应扫描出至少一个冲突组")
        self.assertTrue(any(r["status"] == "ready" for r in gui.conflict_tab.rows))

    def test_conflict_analysis_full_flow(self):
        working = os.path.join(TEST_SVN, "01_TowBat.prefab.working")
        gui.conflict_tab.on_drop(_DropEvent(working))
        # load_working 会自动起后台分析线程；轮询直到完成
        done = _wait_until(self.root, lambda: not gui.conflict_tab.busy)
        self.assertTrue(done, "分析应已结束并复位 busy")
        self.assertEqual(gui.conflict_tab.rows[0]["status"], "done")
        self.assertIn("summary", gui.conflict_tab.rows[0])

    # ── 页签切换 ──
    def test_tab_change_switches_recent_dir(self):
        gui.notebook.select(1)
        _drain(self.root)
        self.assertEqual(gui.shell.current_reports_dir, gui_shell.CONFLICT_REPORTS_DIR)
        gui.notebook.select(0)
        _drain(self.root)
        self.assertEqual(gui.shell.current_reports_dir, gui_shell.COMPARE_REPORTS_DIR)


def _count_html(directory):
    if not os.path.isdir(directory):
        return 0
    return len([f for f in os.listdir(directory) if f.endswith(".html")])


def _svn(args, cwd=None):
    subprocess.run(["svn", "--non-interactive"] + args, cwd=cwd, check=True, capture_output=True)


@unittest.skipUnless(svnh.svn_available(), "svn 命令不可用，跳过 SVN 页签冒烟")
class SvnTabSmokeTest(_GuiTestBase):
    """版本对比 / 分支对比页签：建本地临时 svn 仓库驱动真实流程。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="pfbdiff_guisvn_")
        repo = os.path.join(cls.tmp, "repo")
        wc = os.path.join(cls.tmp, "wc")
        subprocess.run(["svnadmin", "create", repo], check=True, capture_output=True)
        cls.repo_url = pathlib.Path(repo).as_uri()
        _svn(["checkout", cls.repo_url, wc])

        with open(os.path.join(FIXTURES, "comprehensive_before.prefab"), "rb") as f:
            before = f.read()
        with open(os.path.join(FIXTURES, "comprehensive_after.prefab"), "rb") as f:
            cls.after = f.read()

        os.makedirs(os.path.join(wc, "trunk"))
        cls.trunk_file = os.path.join(wc, "trunk", "foo.prefab")
        with open(cls.trunk_file, "wb") as fp:
            fp.write(before)
        os.makedirs(os.path.join(wc, "branches"))
        _svn(["add", "trunk", "branches"], cwd=wc)
        _svn(["commit", "-m", "r1"], cwd=wc)
        _svn(["update"], cwd=wc)
        _svn(["copy", "trunk", os.path.join("branches", "exp")], cwd=wc)
        with open(os.path.join(wc, "branches", "exp", "foo.prefab"), "wb") as fp:
            fp.write(cls.after)
        _svn(["commit", "-m", "r2 branch"], cwd=wc)
        _svn(["update"], cwd=wc)
        cls.repo_root = svnh.info(cls.trunk_file)["repo_root"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_revision_tab_compare_writes_report(self):
        tab = gui.revision_tab
        # 工作副本里把 trunk 文件改成 after（未提交），制造 r1 ↔ 工作副本 的差异
        with open(self.trunk_file, "wb") as fp:
            fp.write(self.after)
        tab.on_drop(_DropEvent(self.trunk_file))
        # 左=最旧的 revision（r1=before），右=工作副本（after）
        tab.left_cb.current(len(tab.specs) - 1)
        tab.right_cb.current(0)

        before_n = _count_html(gui_shell.REVISION_REPORTS_DIR)
        tab.do_compare()
        ok = _wait_until(self.root, lambda: not tab.busy)
        self.assertTrue(ok, "版本对比应结束并复位 busy")
        self.assertEqual(_count_html(gui_shell.REVISION_REPORTS_DIR), before_n + 1)
        # 还原工作副本，避免影响别的用例
        _svn(["revert", self.trunk_file])


if __name__ == "__main__":
    unittest.main(verbosity=2)
