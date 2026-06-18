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
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
TEST_SVN = os.path.join(ROOT, "testSvn")

import gui


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


class GuiSmokeTest(unittest.TestCase):
    def setUp(self):
        # messagebox.* 是阻塞式模态弹窗，无头测试若真弹出会一直等人点 OK。
        # 必须在 build_app 前就 stub 掉所有弹窗，让回调里的提示全部静默。
        self._orig_box = {name: getattr(gui.messagebox, name)
                          for name in ("showinfo", "showwarning", "showerror")}
        for name in self._orig_box:
            setattr(gui.messagebox, name, lambda *a, **k: None)

        # 复位模块级全局，避免上一个用例的残留状态串场
        gui.state = gui.AppState()
        gui.conflict_rows = []
        gui.conflict_busy = False

        # 每个用例独立构建一次窗口（shell 在 build_app 内创建）
        self.root = gui.build_app()
        self.root.withdraw()
        # 拦截开浏览器副作用：shell 是新实例，覆盖其方法即可，无需还原
        gui.shell.open_report = lambda p: None

    def tearDown(self):
        # 等后台分析线程收尾，避免它的 root.after 回调打到已销毁的窗口
        _wait_until(self.root, lambda: not gui.conflict_busy, timeout=30.0)
        for name, fn in self._orig_box.items():
            setattr(gui.messagebox, name, fn)
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

    # ── 框架 ──
    def test_build_app_constructs_both_tabs(self):
        # build_app 跑通即说明两个页签 + 框架控件全部接线成功
        self.assertEqual(len(gui.notebook.tabs()), 2)
        self.assertIsNotNone(gui.gen_btn)
        self.assertIsNotNone(gui.analyze_all_btn)

    # ── 两方对比 ──
    def test_drop_enables_generate_and_writes_report(self):
        gui.on_drop_before(_DropEvent(os.path.join(FIXTURES, "comprehensive_before.prefab")))
        gui.on_drop_after(_DropEvent(os.path.join(FIXTURES, "comprehensive_after.prefab")))
        self.assertEqual(gui.gen_btn["state"], "normal")

        before = _count_html(gui.COMPARE_REPORTS_DIR)
        gui.do_generate()
        after = _count_html(gui.COMPARE_REPORTS_DIR)
        self.assertEqual(after, before + 1, "do_generate 应写出一份 html 报告")

    def test_remove_reverts_to_dropzone(self):
        gui.on_drop_before(_DropEvent(os.path.join(FIXTURES, "comprehensive_before.prefab")))
        self.assertEqual(gui.gen_btn["state"], "normal" if gui.state.after_file else "disabled")
        gui.remove_before()
        self.assertIsNone(gui.state.before_file)
        self.assertEqual(gui.gen_btn["state"], "disabled")

    def test_non_prefab_drop_is_rejected(self):
        gui.on_drop_before(_DropEvent(os.path.join(FIXTURES, "does_not_exist.txt")))
        self.assertIsNone(gui.state.before_file)

    # ── SVN 冲突分析 ──
    def test_conflict_dir_scan_populates_rows(self):
        gui.on_drop_conflict(_DropEvent(TEST_SVN))
        self.assertTrue(len(gui.conflict_rows) >= 1, "应扫描出至少一个冲突组")
        self.assertTrue(any(r["status"] == "ready" for r in gui.conflict_rows))

    def test_conflict_analysis_full_flow(self):
        working = os.path.join(TEST_SVN, "01_TowBat.prefab.working")
        gui.on_drop_conflict(_DropEvent(working))
        # load_conflict_working 会自动起后台分析线程；轮询直到完成
        done = _wait_until(self.root, lambda: not gui.conflict_busy)
        self.assertTrue(done, "分析应已结束并复位 busy")
        self.assertEqual(gui.conflict_rows[0]["status"], "done")
        self.assertIn("summary", gui.conflict_rows[0])

    # ── 页签切换 ──
    def test_tab_change_switches_recent_dir(self):
        gui.notebook.select(1)
        _drain(self.root)
        self.assertEqual(gui.shell.current_reports_dir, gui.CONFLICT_REPORTS_DIR)
        gui.notebook.select(0)
        _drain(self.root)
        self.assertEqual(gui.shell.current_reports_dir, gui.COMPARE_REPORTS_DIR)


def _count_html(directory):
    if not os.path.isdir(directory):
        return 0
    return len([f for f in os.listdir(directory) if f.endswith(".html")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
