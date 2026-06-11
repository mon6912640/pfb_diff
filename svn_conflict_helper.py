#!/usr/bin/env python3
"""
svn_conflict_helper.py — SVN prefab 冲突快速分析脚本

用法：
    # 指定 working 文件，自动寻找同组的 merge-left / merge-right
    python svn_conflict_helper.py ZdlsMapScene.prefab.working

    # 扫描当前目录所有冲突组
    python svn_conflict_helper.py --scan

    # 指定输出目录（默认脚本所在目录的 reports/）
    python svn_conflict_helper.py ZdlsMapScene.prefab.working --out-dir ./reports
"""

import argparse
import html
import os
import sys
import re
import time
from typing import Any, Dict, List, Tuple

# ── 项目根目录 ──
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from diff_engine import diff_prefabs
from report_html_tree import write_html_report


# ═══════════════════════════════════════
# 扫描冲突文件组
# ═══════════════════════════════════════

def find_conflict_groups(directory: str) -> List[Dict[str, str]]:
    """扫描目录，识别 SVN 冲突文件组"""
    groups = []
    files = os.listdir(directory)

    for f in files:
        if not f.endswith(".working"):
            continue
        if ".prefab." not in f:
            continue

        # 前缀示例: ZdlsMapScene.prefab
        prefix = f[: -len(".working")]
        base_pat = re.compile(re.escape(prefix) + r"\.merge-left\.r\d+")
        theirs_pat = re.compile(re.escape(prefix) + r"\.merge-right\.r\d+")

        base_file = None
        theirs_file = None
        for candidate in files:
            if base_pat.match(candidate):
                base_file = candidate
            elif theirs_pat.match(candidate):
                theirs_file = candidate

        if base_file and theirs_file:
            groups.append({
                "name": prefix,
                "base": os.path.join(directory, base_file),
                "ours": os.path.join(directory, f),
                "theirs": os.path.join(directory, theirs_file),
            })

    return groups


def find_group_by_working(working_path: str) -> Dict[str, str]:
    """通过 .working 文件定位同组文件"""
    directory = os.path.dirname(working_path) or "."
    working_name = os.path.basename(working_path)

    if not working_name.endswith(".working"):
        raise SystemExit(f"❌ 输入文件必须以 .working 结尾: {working_path}")

    prefix = working_name[: -len(".working")]
    base_pat = re.compile(re.escape(prefix) + r"\.merge-left\.r\d+")
    theirs_pat = re.compile(re.escape(prefix) + r"\.merge-right\.r\d+")

    base_file = None
    theirs_file = None
    for candidate in os.listdir(directory):
        if base_pat.match(candidate):
            base_file = os.path.join(directory, candidate)
        elif theirs_pat.match(candidate):
            theirs_file = os.path.join(directory, candidate)

    if not base_file:
        raise SystemExit(f"❌ 未找到 merge-left 文件（前缀: {prefix}）")
    if not theirs_file:
        raise SystemExit(f"❌ 未找到 merge-right 文件（前缀: {prefix}）")

    return {
        "name": prefix,
        "base": base_file,
        "ours": working_path,
        "theirs": theirs_file,
    }


# ═══════════════════════════════════════
# 分析逻辑
# ═══════════════════════════════════════

def _change_key(change) -> str:
    """节点关联键。优先 internal_path（带 sibling_index，可区分同名兄弟），其次展示 path。"""
    return str(
        change.before_internal_path or change.before_path
        or change.after_internal_path or change.after_path
        or "_unknown_"
    )


def _display_path(change) -> str:
    """报告里展示用的友好路径"""
    return str(change.before_path or change.after_path or "_unknown_")


def _group_changes(changes: List[Any]) -> Tuple[Dict[str, List[Any]], Dict[str, str]]:
    """按节点键归类变更。warning 类变更没有节点路径，单独排除，避免聚成假节点。"""
    by_node: Dict[str, List[Any]] = {}
    display: Dict[str, str] = {}
    for c in changes:
        if c.category == "warning":
            continue
        k = _change_key(c)
        by_node.setdefault(k, []).append(c)
        display.setdefault(k, _display_path(c))
    return by_node, display


def _signatures(changes: List[Any]) -> set:
    """变更集合的归一化签名，用于判断双方是否做了完全相同的修改。

    match 类条目（uncertain/ambiguous）是匹配元信息而非真实修改，不参与比较。
    after_path 纳入签名，使移动/重命名到不同位置时不会被误判为一致。
    """
    return {
        (c.category, c.type, c.field, repr(c.before), repr(c.after), c.after_path)
        for c in changes
        if c.category != "match"
    }


def _subtree_ops(changes: List[Any]) -> List[Dict[str, Any]]:
    """提取会使整棵子树消失或换位的节点级操作（删除 / 移动 / 移动并重命名）"""
    ops = []
    for c in changes:
        if c.category == "node" and c.type in ("deleted", "moved", "moved_and_renamed"):
            ops.append({
                "key": _change_key(c),
                "path": _display_path(c),
                "op_type": c.type,
                "change": c,
            })
    return ops


def _find_tree_conflicts(ops: List[Dict[str, Any]], other_by_node: Dict[str, List[Any]],
                         other_display: Dict[str, str], op_side: str) -> List[Dict[str, Any]]:
    """一方删除/移动了子树，另一方却修改了子树内部节点 → 树级冲突"""
    conflicts = []
    for op in ops:
        prefix = op["key"] + "/"
        hit_keys = sorted(k for k in other_by_node if k.startswith(prefix))
        if hit_keys:
            conflicts.append({
                "op_side": op_side,
                "op_type": op["op_type"],
                "path": op["path"],
                "key": op["key"],
                "affected": [
                    {"key": k, "path": other_display[k], "changes": other_by_node[k]}
                    for k in hit_keys
                ],
            })
    return conflicts


def analyze_conflict(group: Dict[str, str]) -> Dict[str, Any]:
    """分析一个冲突组，返回综合数据"""
    print(f"\n📦 冲突组: {group['name']}")
    print(f"   base:   {group['base']}")
    print(f"   ours:   {group['ours']}")
    print(f"   theirs: {group['theirs']}")

    print("   ⏳ 计算 base → ours ...")
    ours_result = diff_prefabs(group["base"], group["ours"])

    print("   ⏳ 计算 base → theirs ...")
    theirs_result = diff_prefabs(group["base"], group["theirs"])

    print("   ⏳ 计算 ours ↔ theirs（参考视图）...")
    cross_result = diff_prefabs(group["ours"], group["theirs"])

    # 按节点归类
    ours_by_node, ours_display = _group_changes(ours_result.changes)
    theirs_by_node, theirs_display = _group_changes(theirs_result.changes)
    display = {**theirs_display, **ours_display}

    # 树级冲突：一方删/移子树，另一方改其内部节点
    tree_conflicts = (
        _find_tree_conflicts(_subtree_ops(ours_result.changes), theirs_by_node, theirs_display, "ours")
        + _find_tree_conflicts(_subtree_ops(theirs_result.changes), ours_by_node, ours_display, "theirs")
    )
    tree_affected_keys = set()
    for tc in tree_conflicts:
        tree_affected_keys.update(item["key"] for item in tc["affected"])

    # 交叉分类
    only_ours = []
    only_theirs = []
    both_modified = []     # 双方修改且结果不同 → 真冲突
    both_convergent = []   # 双方修改且结果一致 → 假冲突，任取一边

    all_keys = set(ours_by_node.keys()) | set(theirs_by_node.keys())
    for key in sorted(all_keys):
        o = ours_by_node.get(key, [])
        t = theirs_by_node.get(key, [])
        path = display.get(key, key)
        if o and t:
            if _signatures(o) == _signatures(t):
                both_convergent.append({"path": path, "key": key, "changes": o})
            else:
                both_modified.append({"path": path, "key": key, "ours": o, "theirs": t})
        elif o:
            # 被对方树级操作覆盖的节点不算"安全"，已在树级冲突区展示
            if key not in tree_affected_keys:
                only_ours.append({"path": path, "key": key, "changes": o})
        else:
            if key not in tree_affected_keys:
                only_theirs.append({"path": path, "key": key, "changes": t})

    # 独立报告文件名
    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in group["name"])

    return {
        "group": group,
        "stamp": stamp,
        "safe_name": safe_name,
        "ours_result": ours_result,
        "theirs_result": theirs_result,
        "cross_result": cross_result,
        "only_ours": only_ours,
        "only_theirs": only_theirs,
        "both_modified": both_modified,
        "both_convergent": both_convergent,
        "tree_conflicts": tree_conflicts,
        "summary": {
            "only_ours_nodes": len(only_ours),
            "only_theirs_nodes": len(only_theirs),
            "both_modified_nodes": len(both_modified),
            "convergent_nodes": len(both_convergent),
            "tree_conflicts": len(tree_conflicts),
            "ours_changes_total": len(ours_result.changes),
            "theirs_changes_total": len(theirs_result.changes),
            "ours_high_risk": sum(1 for c in ours_result.changes if c.risk == "high"),
            "theirs_high_risk": sum(1 for c in theirs_result.changes if c.risk == "high"),
            "ours_medium_risk": sum(1 for c in ours_result.changes if c.risk == "medium"),
            "theirs_medium_risk": sum(1 for c in theirs_result.changes if c.risk == "medium"),
        },
    }


# ═══════════════════════════════════════
# HTML 报告生成
# ═══════════════════════════════════════

def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


_TABLE_HEAD = """<thead><tr style="text-align:left;color:#94a3b8;border-bottom:1px solid #475569;">
  <th style="padding:4px 8px;">category</th><th>type</th><th>risk</th><th>field</th><th>before</th><th>after</th>
</tr></thead>"""


def _change_rows(changes: List[Any]) -> str:
    rows = []
    for c in changes:
        risk_color = {"high": "#ef4444", "medium": "#f59e0b", "low": "#22c55e"}.get(c.risk, "#94a3b8")
        before_text = _esc(str(c.before)[:80]) if c.before is not None else "-"
        after_text = _esc(str(c.after)[:80]) if c.after is not None else "-"
        rows.append(f"""
        <tr>
          <td style="padding:4px 8px;border-bottom:1px solid #334155;color:#e2e8f0;">{_esc(c.category)}</td>
          <td style="padding:4px 8px;border-bottom:1px solid #334155;color:#e2e8f0;">{_esc(c.type)}</td>
          <td style="padding:4px 8px;border-bottom:1px solid #334155;"><span style="color:{risk_color};font-weight:bold;text-transform:uppercase;font-size:11px;">{_esc(c.risk)}</span></td>
          <td style="padding:4px 8px;border-bottom:1px solid #334155;color:#94a3b8;font-size:12px;font-family:monospace;">{_esc(c.field) if c.field else "-"}</td>
          <td style="padding:4px 8px;border-bottom:1px solid #334155;color:#94a3b8;font-size:12px;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{before_text}</td>
          <td style="padding:4px 8px;border-bottom:1px solid #334155;color:#94a3b8;font-size:12px;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{after_text}</td>
        </tr>
        """)
    return "\n".join(rows)


def _change_table(changes: List[Any]) -> str:
    return f"""<table style="width:100%;border-collapse:collapse;font-size:12px;">
      {_TABLE_HEAD}
      <tbody>{_change_rows(changes)}</tbody>
    </table>"""


_OP_LABELS = {"deleted": "删除", "moved": "移动", "moved_and_renamed": "移动并重命名"}
_SIDE_LABELS = {"ours": "Ours（本地）", "theirs": "Theirs（分支）"}


def _build_overview_html(data: Dict[str, Any], ours_report_name: str,
                         theirs_report_name: str, cross_report_name: str) -> str:
    s = data["summary"]
    group = data["group"]

    # 树级冲突区域
    tree_sections = []
    for tc in data["tree_conflicts"]:
        op_label = _OP_LABELS.get(tc["op_type"], tc["op_type"])
        op_side = _SIDE_LABELS.get(tc["op_side"], tc["op_side"])
        other_side = _SIDE_LABELS["theirs" if tc["op_side"] == "ours" else "ours"]
        affected_html = "\n".join(
            f"""<div style="margin-top:8px;">
              <div style="color:#fbbf24;font-size:12px;font-family:monospace;margin-bottom:4px;">{_esc(item['path'])}</div>
              {_change_table(item['changes'])}
            </div>"""
            for item in tc["affected"]
        )
        tree_sections.append(f"""
        <div style="background:#1c1207;border:1px solid #92400e;border-radius:8px;padding:12px;margin-bottom:12px;">
          <div style="color:#fbbf24;font-weight:bold;font-size:14px;margin-bottom:4px;">
            🌳 {op_side} {op_label}了子树 <span style="font-family:monospace;">{_esc(tc['path'])}</span>，
            但 {other_side} 修改了其内部 {len(tc['affected'])} 个节点
          </div>
          <div style="color:#94a3b8;font-size:12px;margin-bottom:4px;">
            这些内部修改在合并后将无处安放（或随子树换位而失效），必须人工决定取舍。
          </div>
          {affected_html}
        </div>
        """)

    # 真冲突区域
    conflict_sections = []
    for item in data["both_modified"]:
        conflict_sections.append(f"""
        <div style="background:#1f1010;border:1px solid #7f1d1d;border-radius:8px;padding:12px;margin-bottom:12px;">
          <div style="color:#fca5a5;font-weight:bold;font-size:14px;margin-bottom:8px;">⚠️ {_esc(item['path'])}</div>
          <div style="display:flex;gap:16px;">
            <div style="flex:1;">
              <div style="color:#60a5fa;font-size:12px;font-weight:bold;margin-bottom:4px;">⬅ Ours 修改 ({len(item['ours'])} 条)</div>
              {_change_table(item['ours'])}
            </div>
            <div style="flex:1;">
              <div style="color:#34d399;font-size:12px;font-weight:bold;margin-bottom:4px;">➡ Theirs 修改 ({len(item['theirs'])} 条)</div>
              {_change_table(item['theirs'])}
            </div>
          </div>
        </div>
        """)

    # 双方改动一致区域（假冲突）
    convergent_sections = []
    for item in data["both_convergent"]:
        convergent_sections.append(f"""
        <div style="background:#0d1a12;border:1px solid #166534;border-radius:6px;padding:8px;margin-bottom:6px;">
          <div style="color:#4ade80;font-weight:bold;font-size:13px;margin-bottom:4px;">✓ {_esc(item['path'])}
            <span style="color:#94a3b8;font-weight:normal;font-size:12px;">— 双方做了完全相同的修改，任取一边即可</span>
          </div>
          {_change_table(item['changes'])}
        </div>
        """)

    # 仅单边修改区域
    def _side_sections(items: List[Dict[str, Any]], safe_border: str) -> str:
        sections = []
        for item in items:
            has_risk = any(c.risk in ("high", "medium") for c in item["changes"])
            border_color = "#7f1d1d" if has_risk else safe_border
            bg_color = "#1a1010" if has_risk else "#0f172a"
            sections.append(f"""
            <div style="background:{bg_color};border:1px solid {border_color};border-radius:6px;padding:8px;margin-bottom:6px;">
              <div style="color:#e2e8f0;font-weight:bold;font-size:13px;margin-bottom:4px;">{_esc(item['path'])}</div>
              {_change_table(item['changes'])}
            </div>
            """)
        return "\n".join(sections) if sections else '<div style="color:#64748b;padding:12px;">无</div>'

    has_real_conflict = bool(data["both_modified"]) or bool(data["tree_conflicts"])
    tree_html = "\n".join(tree_sections)
    conflict_html = "\n".join(conflict_sections)
    if not has_real_conflict:
        conflict_html = '<div style="color:#64748b;padding:20px;text-align:center;">🎉 没有检测到真冲突：双方没有以不同方式修改同一节点，也没有树级冲突。可机械合并。</div>'
    convergent_html = "\n".join(convergent_sections)
    ours_html = _side_sections(data["only_ours"], "#1e3a5f")
    theirs_html = _side_sections(data["only_theirs"], "#064e3b")

    convergent_block = f"""
  <div class="section">
    <h2>🟩 双方改动一致 <span class="badge badge-green">{s['convergent_nodes']} nodes</span></h2>
    <p style="color:#64748b;font-size:13px;margin-top:-8px;margin-bottom:12px;">双方都修改了这些节点，但改成了相同结果（假冲突）。合并时任取一边即可。</p>
    {convergent_html}
  </div>
    """ if data["both_convergent"] else ""

    tree_block = f"""
  <div class="section">
    <h2>🌳 树级冲突 <span class="badge badge-orange">{s['tree_conflicts']} 处</span></h2>
    <p style="color:#64748b;font-size:13px;margin-top:-8px;margin-bottom:12px;">一方删除或移动了整棵子树，另一方却修改了子树内部的节点。按节点对碰发现不了这类冲突，需要特别注意。</p>
    {tree_html}
  </div>
    """ if data["tree_conflicts"] else ""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>SVN Conflict Overview — {_esc(group['name'])}</title>
<style>
  body {{ margin:0; font-family: "Microsoft YaHei", "Segoe UI", sans-serif; background:#0b1120; color:#e2e8f0; }}
  .container {{ max-width:1400px; margin:0 auto; padding:20px; }}
  h1 {{ margin:0 0 8px; font-size:20px; }}
  h2 {{ margin:24px 0 12px; font-size:16px; color:#94a3b8; border-bottom:1px solid #334155; padding-bottom:6px; }}
  .meta {{ color:#64748b; font-size:13px; margin-bottom:16px; }}
  .stat-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:12px; margin-bottom:24px; }}
  .stat-card {{ background:#111827; border:1px solid #334155; border-radius:8px; padding:12px; text-align:center; }}
  .stat-value {{ font-size:24px; font-weight:bold; margin-bottom:4px; }}
  .stat-label {{ font-size:12px; color:#94a3b8; }}
  .links {{ margin-bottom:24px; }}
  .links a {{ display:inline-block; background:#1e3a5f; color:#60a5fa; padding:8px 16px; border-radius:6px; text-decoration:none; margin-right:8px; margin-bottom:8px; font-size:13px; }}
  .links a:hover {{ background:#2563eb; color:#fff; }}
  .section {{ margin-bottom:32px; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:bold; margin-left:8px; }}
  .badge-red {{ background:#7f1d1d; color:#fca5a5; }}
  .badge-blue {{ background:#1e3a5f; color:#60a5fa; }}
  .badge-green {{ background:#064e3b; color:#34d399; }}
  .badge-orange {{ background:#92400e; color:#fbbf24; }}
</style>
</head>
<body>
<div class="container">
  <h1>🌲 SVN 冲突概览 — {_esc(group['name'])}</h1>
  <div class="meta">
    base: {_esc(os.path.basename(group['base']))} &nbsp;|&nbsp;
    ours: {_esc(os.path.basename(group['ours']))} &nbsp;|&nbsp;
    theirs: {_esc(os.path.basename(group['theirs']))} &nbsp;|&nbsp;
    生成时间: {data['stamp']}
  </div>

  <div class="links">
    <a href="{ours_report_name}" target="_blank">📄 base → ours 完整报告</a>
    <a href="{theirs_report_name}" target="_blank">📄 base → theirs 完整报告</a>
    <a href="{cross_report_name}" target="_blank">📄 ours ↔ theirs 直接对比（参考：两个终态的差异，不区分谁改的）</a>
  </div>

  <div class="stat-grid">
    <div class="stat-card">
      <div class="stat-value" style="color:#ef4444;">{s['both_modified_nodes']}</div>
      <div class="stat-label">真冲突节点<br><small style="color:#ef4444;">双方改法不同</small></div>
    </div>
    <div class="stat-card">
      <div class="stat-value" style="color:#fbbf24;">{s['tree_conflicts']}</div>
      <div class="stat-label">树级冲突<br><small style="color:#fbbf24;">删/移子树 vs 改内部</small></div>
    </div>
    <div class="stat-card">
      <div class="stat-value" style="color:#4ade80;">{s['convergent_nodes']}</div>
      <div class="stat-label">双方改动一致<br><small style="color:#4ade80;">假冲突，任取一边</small></div>
    </div>
    <div class="stat-card">
      <div class="stat-value" style="color:#60a5fa;">{s['only_ours_nodes']}</div>
      <div class="stat-label">仅 ours 修改<br><small style="color:#60a5fa;">可安全保留</small></div>
    </div>
    <div class="stat-card">
      <div class="stat-value" style="color:#34d399;">{s['only_theirs_nodes']}</div>
      <div class="stat-label">仅 theirs 修改<br><small style="color:#34d399;">可安全合入</small></div>
    </div>
    <div class="stat-card">
      <div class="stat-value" style="color:#f59e0b;">{s['ours_high_risk']} / {s['theirs_high_risk']}</div>
      <div class="stat-label">高风险变更<br><small>ours / theirs</small></div>
    </div>
    <div class="stat-card">
      <div class="stat-value" style="color:#e2e8f0;">{s['ours_changes_total']} / {s['theirs_changes_total']}</div>
      <div class="stat-label">变更总数<br><small>ours / theirs</small></div>
    </div>
  </div>

  {tree_block}

  <div class="section">
    <h2>🔴 真冲突区域 <span class="badge badge-red">{s['both_modified_nodes']} nodes</span></h2>
    <p style="color:#64748b;font-size:13px;margin-top:-8px;margin-bottom:12px;">以下节点在 base 基础上，被两边以不同方式修改过。需要人工判断保留哪边，或在编辑器中重做合并。</p>
    {conflict_html}
  </div>

  {convergent_block}

  <div style="display:flex;gap:24px;">
    <div style="flex:1;" class="section">
      <h2>🔵 仅 ours 修改 <span class="badge badge-blue">{s['only_ours_nodes']} nodes</span></h2>
      <p style="color:#64748b;font-size:13px;margin-top:-8px;margin-bottom:12px;">这些节点只有 ours 修改了，合入时可直接保留。</p>
      <div style="max-height:600px;overflow-y:auto;">{ours_html}</div>
    </div>
    <div style="flex:1;" class="section">
      <h2>🟢 仅 theirs 修改 <span class="badge badge-green">{s['only_theirs_nodes']} nodes</span></h2>
      <p style="color:#64748b;font-size:13px;margin-top:-8px;margin-bottom:12px;">这些节点只有 theirs 修改了，合入时可直接采纳。</p>
      <div style="max-height:600px;overflow-y:auto;">{theirs_html}</div>
    </div>
  </div>

  <div style="margin-top:32px;padding:16px;background:#111827;border:1px solid #334155;border-radius:8px;color:#94a3b8;font-size:13px;">
    <strong style="color:#e2e8f0;">💡 使用建议</strong><br>
    1. 优先处理<strong style="color:#fbbf24;">树级冲突</strong>和<strong style="color:#ef4444;">真冲突区域</strong>，这两类必须人工决定取舍。<br>
    2. <strong style="color:#4ade80;">双方改动一致</strong>的节点是假冲突，任取一边即可。<br>
    3. 对于真冲突，建议放弃自动合并，在 Cocos Creator 中手动应用一方的修改。<br>
    4. 点击上方链接查看完整树形报告，可精确定位字段级差异。
  </div>
</div>
</body>
</html>
"""


def generate_reports(data: Dict[str, Any], out_dir: str) -> str:
    """生成概览报告 + 三份独立报告，返回概览报告路径"""
    os.makedirs(out_dir, exist_ok=True)

    safe = data["safe_name"]
    stamp = data["stamp"]

    # 独立报告
    ours_name = f"{safe}_ours_{stamp}.html"
    theirs_name = f"{safe}_theirs_{stamp}.html"
    cross_name = f"{safe}_ours_vs_theirs_{stamp}.html"
    ours_path = os.path.join(out_dir, ours_name)
    theirs_path = os.path.join(out_dir, theirs_name)
    cross_path = os.path.join(out_dir, cross_name)

    write_html_report(data["ours_result"], ours_path)
    write_html_report(data["theirs_result"], theirs_path)
    write_html_report(data["cross_result"], cross_path)
    print(f"   ✓ base → ours:   {ours_path}")
    print(f"   ✓ base → theirs: {theirs_path}")
    print(f"   ✓ ours ↔ theirs: {cross_path}")

    # 概览报告
    overview_name = f"{safe}_conflict_overview_{stamp}.html"
    overview_path = os.path.join(out_dir, overview_name)
    html_text = _build_overview_html(data, ours_name, theirs_name, cross_name)
    with open(overview_path, "w", encoding="utf-8") as f:
        f.write(html_text)
    print(f"   ✓ 冲突概览:      {overview_path}")

    return overview_path


# ═══════════════════════════════════════
# 主入口
# ═══════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="SVN prefab 冲突快速分析")
    parser.add_argument("target", nargs="?", help=".working 文件路径，或目录路径（配合 --scan）")
    parser.add_argument("--scan", action="store_true", help="扫描目录内所有冲突组")
    parser.add_argument("--out-dir", default=os.path.join(PROJECT_ROOT, "reports"), help="输出目录（默认脚本所在目录的 reports/）")
    args = parser.parse_args()

    # 收集冲突组
    if args.scan:
        scan_dir = args.target or "."
        groups = find_conflict_groups(scan_dir)
        if not groups:
            print(f"未在 {scan_dir} 发现 SVN 冲突文件组")
            return
    else:
        if not args.target:
            parser.print_help()
            return
        groups = [find_group_by_working(args.target)]

    # 逐组分析（单组失败不中断整批）
    print(f"\n发现 {len(groups)} 个冲突组，开始分析...")
    overview_paths = []
    failed = []
    for group in groups:
        try:
            data = analyze_conflict(group)
            path = generate_reports(data, args.out_dir)
            overview_paths.append(path)
        except Exception as e:
            print(f"   ❌ 分析失败: {e}")
            failed.append((group["name"], str(e)))

    print(f"\n✅ 完成 {len(overview_paths)}/{len(groups)} 组")
    for p in overview_paths:
        print(f"   📄 {p}")
    if failed:
        print("\n⚠️ 以下冲突组分析失败:")
        for name, err in failed:
            print(f"   {name}: {err}")
        sys.exit(4)


if __name__ == "__main__":
    main()
