#!/usr/bin/env python3
"""svn_revision_helper 的真实端到端测试。

开发机装了 svn，但本仓库是 git、不是 SVN 工作副本，所以这里**自建一个本地
临时 SVN 仓库**（svnadmin create + file:/// URL，无网络、确定性）：提交两个
版本 + 一个分支，覆盖 info / log / cat / list_branches 全链路，并验证取出的
内容能正确喂给 diff_engine。

svn 不可用时整个用例集自动 skip，保证无 svn 的环境不报红。
"""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import svn_revision_helper as svnh
from diff_engine import diff_prefabs

FIXTURES = os.path.join(ROOT, "tests", "fixtures")


def _svn(args, cwd=None):
    subprocess.run(["svn", "--non-interactive"] + args, cwd=cwd,
                   check=True, capture_output=True)


def _read(path):
    with open(path, "rb") as f:
        return f.read()


@unittest.skipUnless(svnh.svn_available(), "svn 命令不可用，跳过 SVN 集成测试")
class SvnRevisionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="pfbdiff_svntest_")
        repo_dir = os.path.join(cls.tmp, "repo")
        wc = os.path.join(cls.tmp, "wc")
        subprocess.run(["svnadmin", "create", repo_dir], check=True, capture_output=True)
        cls.repo_url = pathlib.Path(repo_dir).as_uri()  # Windows 下生成 file:///C:/...

        _svn(["checkout", cls.repo_url, wc])
        before = _read(os.path.join(FIXTURES, "comprehensive_before.prefab"))
        after = _read(os.path.join(FIXTURES, "comprehensive_after.prefab"))

        # r1: trunk/foo.prefab = before 内容；同时建空 branches 目录
        os.makedirs(os.path.join(wc, "trunk"))
        cls.trunk_file = os.path.join(wc, "trunk", "foo.prefab")
        with open(cls.trunk_file, "wb") as f:
            f.write(before)
        os.makedirs(os.path.join(wc, "branches"))
        _svn(["add", "trunk", "branches"], cwd=wc)
        _svn(["commit", "-m", "r1 add trunk"], cwd=wc)
        _svn(["update"], cwd=wc)

        # r2: 把 trunk 拷成 branches/exp，并把分支上的文件改成 after 内容
        _svn(["copy", "trunk", os.path.join("branches", "exp")], cwd=wc)
        with open(os.path.join(wc, "branches", "exp", "foo.prefab"), "wb") as f:
            f.write(after)
        _svn(["commit", "-m", "r2 branch exp + edit"], cwd=wc)
        _svn(["update"], cwd=wc)

        cls.wc = wc
        cls.before_bytes = before
        cls.after_bytes = after

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_info_reports_url_root_relpath(self):
        meta = svnh.info(self.trunk_file)
        self.assertTrue(meta["url"].endswith("/trunk/foo.prefab"))
        self.assertEqual(meta["rel_path"], "trunk/foo.prefab")
        self.assertTrue(meta["repo_root"])
        self.assertTrue(meta["rev"])

    def test_log_lists_history_desc(self):
        entries = svnh.log(self.trunk_file)
        self.assertGreaterEqual(len(entries), 1)
        revs = [e["rev"] for e in entries]
        self.assertEqual(revs, sorted(revs, reverse=True))
        self.assertTrue(all("msg" in e for e in entries))

    def test_cat_revision_matches_committed_bytes(self):
        dest = os.path.join(self.tmp, "cat_r1.prefab")
        svnh.cat(self.trunk_file, 1, dest)
        self.assertEqual(_read(dest), self.before_bytes)

    def test_list_branches_finds_exp(self):
        meta = svnh.info(self.trunk_file)
        self.assertIn("exp", svnh.list_branches(meta["repo_root"]))

    def test_cross_branch_cat_and_diff(self):
        meta = svnh.info(self.trunk_file)
        work = svnh.make_workdir()
        try:
            left = svnh.cat(self.trunk_file, "HEAD", os.path.join(work, "left.prefab"))
            branch_url = meta["repo_root"].rstrip("/") + "/branches/exp/foo.prefab"
            right = svnh.cat(branch_url, "HEAD", os.path.join(work, "right.prefab"))
            self.assertEqual(_read(right), self.after_bytes)
            result = diff_prefabs(left, right)
            # before≠after，应产出非空变更
            self.assertTrue(len(result.changes) > 0)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_info_on_non_wc_raises(self):
        with self.assertRaises(svnh.SvnError):
            svnh.info(os.path.join(FIXTURES, "comprehensive_before.prefab"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
