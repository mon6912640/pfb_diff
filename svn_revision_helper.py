#!/usr/bin/env python3
"""svn_revision_helper.py — 对 svn 命令行的薄封装（无 UI）。

供「版本对比」「分支对比」两个 GUI 页签共用：取指定版本/分支的 prefab 内容
到临时文件，再交给 diff_engine 做语义对比。是本项目第一个主动调用外部 svn
命令的模块——前提是目标文件位于一个 SVN 工作副本（WC）内。

所有命令都带 --non-interactive，避免在需要鉴权的仓库上卡住等待输入。
svn 的 --xml 输出固定 UTF-8；这里统一按字节捕获再显式 utf-8 解码，
不依赖 Windows 的本地代码页。
"""

import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from typing import List, Optional


class SvnError(Exception):
    """svn 命令失败或环境不满足时抛出，message 为面向用户的中文说明。"""


def _run(args: List[str]) -> bytes:
    """执行 svn 命令，返回 stdout 字节；非零退出抛 SvnError（带 stderr）。"""
    try:
        proc = subprocess.run(
            ["svn", "--non-interactive"] + args,
            capture_output=True,
        )
    except FileNotFoundError:
        raise SvnError("未找到 svn 命令，请先安装 SVN 命令行客户端并加入 PATH")
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip() or "未知错误"
        raise SvnError(msg)
    return proc.stdout


def svn_available() -> bool:
    """svn 客户端是否可用。"""
    try:
        _run(["--version", "--quiet"])
        return True
    except SvnError:
        return False


def info(path: str) -> dict:
    """svn info --xml，返回 {url, repo_root, rev, rel_path}。

    path 不在 WC 内（或不是受控文件）时 svn 报错，转成 SvnError。
    """
    xml = _run(["info", "--xml", path])
    root = ET.fromstring(xml)
    entry = root.find("entry")
    if entry is None:
        raise SvnError(f"无法获取 svn 信息（文件可能不在 SVN 工作副本内）：{path}")
    url = entry.findtext("url") or ""
    repo_root = entry.findtext("repository/root") or ""
    rev = entry.get("revision") or ""
    rel = entry.findtext("relative-url") or ""
    if rel.startswith("^/"):
        rel = rel[2:]
    return {"url": url, "repo_root": repo_root, "rev": rev, "rel_path": rel}


def log(path: str, limit: int = 50) -> List[dict]:
    """svn log --xml -l N，返回 [{rev:int, author, date, msg}]（按版本降序）。

    历史断裂/较短的仓库（如独立 trunk）只返回已有条目，不报错。
    """
    xml = _run(["log", "--xml", "-l", str(limit), path])
    root = ET.fromstring(xml)
    entries = []
    for e in root.findall("logentry"):
        entries.append({
            "rev": int(e.get("revision")),
            "author": e.findtext("author") or "",
            "date": (e.findtext("date") or "")[:19].replace("T", " "),
            "msg": (e.findtext("msg") or "").strip(),
        })
    return entries


def list_branches(repo_root: str) -> List[str]:
    """best-effort 列出 <repo_root>/branches 下的条目名（标准布局才有）。

    仓库不遵循 trunk/branches 布局、或 branches 不存在时返回 []，绝不抛错——
    跨分支对比始终允许用户手动粘贴完整 URL，自动列举仅作便利。
    """
    try:
        xml = _run(["ls", "--xml", repo_root.rstrip("/") + "/branches"])
    except SvnError:
        return []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    names = []
    for entry in root.findall(".//entry"):
        name = entry.findtext("name")
        if name:
            names.append(name)
    return sorted(names)


def cat(target: str, rev, dest_path: str) -> str:
    """svn cat -r <rev> <target> 写入 dest_path，返回 dest_path。

    target 可为 WC 文件路径或仓库 URL；rev 可为整数、"HEAD" 等。
    """
    data = _run(["cat", "-r", str(rev), target])
    with open(dest_path, "wb") as f:
        f.write(data)
    return dest_path


def make_workdir() -> str:
    """创建一个临时目录用于存放取出的版本文件。用完由调用方 cleanup。"""
    return tempfile.mkdtemp(prefix="pfbdiff_svn_")
