#!/usr/bin/env python3
"""
svn_conflict_helper.py — SVN prefab 冲突快速分析脚本

用法：
    # 指定 working 文件，自动寻找同组的 merge-left / merge-right
    python svn_conflict_helper.py ZdlsMapScene.prefab.working

    # 扫描当前目录所有冲突组
    python svn_conflict_helper.py --scan

    # 指定输出目录（默认脚本所在目录的 reports/svn_conflict/）
    python svn_conflict_helper.py ZdlsMapScene.prefab.working --out-dir ./reports
"""

import argparse
import html
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# ── 项目根目录 ──
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from diff_engine import diff_prefabs
from report_html_tree import write_html_report, _CHANGE_META, _analyze_changes


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
        raise ValueError(f"输入文件必须以 .working 结尾: {working_path}")

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
        raise ValueError(f"未找到 merge-left 文件（前缀: {prefix}）")
    if not theirs_file:
        raise ValueError(f"未找到 merge-right 文件（前缀: {prefix}）")

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


def analyze_conflict(group: Dict[str, str], progress=print) -> Dict[str, Any]:
    """分析一个冲突组，返回综合数据。progress 接收进度文本（GUI 可传回调，CLI 默认 print）。"""
    progress(f"\n📦 冲突组: {group['name']}")
    progress(f"   base:   {group['base']}")
    progress(f"   ours:   {group['ours']}")
    progress(f"   theirs: {group['theirs']}")

    progress("   ⏳ 计算 base → ours ...")
    ours_result = diff_prefabs(group["base"], group["ours"])

    progress("   ⏳ 计算 base → theirs ...")
    theirs_result = diff_prefabs(group["base"], group["theirs"])

    progress("   ⏳ 计算 ours ↔ theirs（参考视图）...")
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
# 字段中文化与值格式化
# ═══════════════════════════════════════

def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


_FIELD_LABELS = {
    "_position": "位置", "_scale": "缩放", "_color": "颜色", "_opacity": "不透明度",
    "_active": "激活", "_contentSize": "尺寸", "_anchorPoint": "锚点",
    "_string": "文本", "_N$string": "文本", "string": "文本",
    "_eulerAngles": "旋转", "_zIndex": "层级", "_name": "名称",
    "_skewX": "斜切X", "_skewY": "斜切Y",
}

_RESOURCE_LABELS = {
    "_spriteFrame": "图片", "_N$normalSprite": "普通态图", "_N$pressedSprite": "按下态图",
    "_N$hoverSprite": "悬停态图", "_N$disabledSprite": "禁用态图",
    "normalSprite": "普通态图", "pressedSprite": "按下态图",
    "hoverSprite": "悬停态图", "disabledSprite": "禁用态图",
    "skeletonData": "骨骼数据", "_defaultClip": "默认动画", "_atlas": "图集",
}

_SUBFIELD_KEYS = {
    "cc.Vec2": ["x", "y"],
    "cc.Vec3": ["x", "y", "z"],
    "cc.Size": ["width", "height"],
    "cc.Color": ["r", "g", "b", "a"],
}

_SUBFIELD_LABELS = {"x": "x", "y": "y", "z": "z", "width": "宽", "height": "高",
                    "r": "R", "g": "G", "b": "B", "a": "Alpha"}

_NODE_TYPE_LABELS = {
    "moved": "父节点", "renamed": "名称", "moved_and_renamed": "父节点+名称",
    "child_order_changed": "子节点顺序",
}

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F-]{20,30}$")


def _field_label(field: Optional[str], category: str) -> str:
    """字段路径 → 中文名"""
    if not field:
        return "—"
    if category == "event":
        return "点击事件"
    if category == "resource":
        # 形如 cc.Sprite._spriteFrame
        comp, _, prop = field.rpartition(".")
        label = _RESOURCE_LABELS.get(prop, prop)
        return f"{label}（{comp}）" if comp else label
    if category == "component":
        # 形如 cc.Sprite#0
        return field.split("#")[0]
    if field.startswith("node.props."):
        prop = field[len("node.props."):]
        return _FIELD_LABELS.get(prop, prop)
    if field.startswith("component."):
        # 形如 component.cc.Sprite#0.props.xxx
        body = field[len("component."):]
        comp, _, prop_part = body.partition(".props.")
        comp = comp.split("#")[0]
        prop = _FIELD_LABELS.get(prop_part, prop_part)
        return f"{comp} · {prop}"
    return field


def _num(v: Any) -> str:
    if isinstance(v, float):
        if v == int(v):
            return str(int(v))
        return f"{v:.4g}"
    return str(v)


def _format_value(v: Any, max_len: int = 60) -> str:
    """把原始值格式化成可读 HTML（内部自行转义）"""
    if v is None:
        return '<span class="val-none">空</span>'
    if isinstance(v, bool):
        return "✓ 是" if v else "✗ 否"
    if isinstance(v, (int, float)):
        return _esc(_num(v))
    if isinstance(v, dict):
        t = v.get("__type__")
        if t in ("cc.Vec2", "cc.Vec3"):
            parts = [_num(v.get("x", 0)), _num(v.get("y", 0))]
            if t == "cc.Vec3" and v.get("z", 0):
                parts.append(_num(v.get("z", 0)))
            return _esc("(" + ", ".join(parts) + ")")
        if t == "cc.Size":
            return _esc(f"{_num(v.get('width', 0))} × {_num(v.get('height', 0))}")
        if t == "cc.Color":
            r, g, b = int(v.get("r", 0)), int(v.get("g", 0)), int(v.get("b", 0))
            return (f'<span class="swatch" style="background:rgb({r},{g},{b})"></span>'
                    f'rgb({r},{g},{b})')
        if "__uuid__" in v:
            return _format_value(v["__uuid__"], max_len)
    if isinstance(v, str):
        if _UUID_RE.match(v):
            return f'<span class="mono" title="{_esc(v)}">{_esc(v[:8])}…</span>'
        text = f'"{v}"'
        if len(text) > max_len:
            return f'<span title="{_esc(text)}">{_esc(text[:max_len])}…</span>'
        return _esc(text)
    # 列表 / 复杂对象：JSON 摘要 + title 放全文
    try:
        text = json.dumps(v, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(v)
    if len(text) > max_len:
        return f'<span class="mono" title="{_esc(text[:800])}">{_esc(text[:max_len])}…</span>'
    return f'<span class="mono">{_esc(text)}</span>'


# ═══════════════════════════════════════
# 变更 → 原子行（字段级展示单元）
# ═══════════════════════════════════════

def _badge_of(change) -> Dict[str, str]:
    meta = _CHANGE_META.get((change.category, change.type))
    if meta:
        return {"label": meta[1], "color": meta[2]}
    return {"label": change.type, "color": "#94a3b8"}


def _split_subfields(change) -> Optional[List[Tuple[str, Any, Any]]]:
    """Vec/Size/Color 这类结构值拆成分量级变化，便于识别'双方改的是同一向量的不同分量'"""
    if not (isinstance(change.before, dict) and isinstance(change.after, dict)):
        return None
    t = change.before.get("__type__")
    if not t or t != change.after.get("__type__") or t not in _SUBFIELD_KEYS:
        return None
    subs = []
    for k in _SUBFIELD_KEYS[t]:
        bv, av = change.before.get(k), change.after.get(k)
        if bv != av:
            subs.append((k, bv, av))
    return subs or None


def _change_atoms(change) -> List[Dict[str, Any]]:
    """把一条 Change 拆成一个或多个原子行：{key, label, badge, html(双值) , cmp(碰撞比较值)}"""
    badge = _badge_of(change)
    atoms = []

    if change.category == "node":
        if change.type in ("moved", "renamed", "moved_and_renamed"):
            if change.type == "renamed":
                before, after = change.details.get("before_name"), change.details.get("after_name")
            else:
                before, after = change.before_path, change.after_path
            atoms.append({
                "key": ("node", change.type), "label": _NODE_TYPE_LABELS[change.type], "badge": badge,
                "html": f'<span class="diff-old">{_esc(before)}</span><span class="arr">→</span><span class="diff-new">{_esc(after)}</span>',
                "cmp": repr(change.after_path),
            })
        elif change.type == "deleted":
            atoms.append({
                "key": ("node", "deleted"), "label": "节点", "badge": badge,
                "html": '<span class="diff-old">整个节点被删除</span>', "cmp": "deleted",
            })
        elif change.type == "added":
            atoms.append({
                "key": ("node", "added"), "label": "节点", "badge": badge,
                "html": '<span class="diff-new">新增节点</span>', "cmp": "added",
            })
        elif change.type == "child_order_changed":
            atoms.append({
                "key": ("node", "child_order_changed"), "label": "子节点顺序", "badge": badge,
                "html": f'{_format_value(change.before)}<span class="arr">→</span>{_format_value(change.after)}',
                "cmp": repr(change.after),
            })
        return atoms

    if change.category == "component" and change.type in ("added", "deleted"):
        comp = change.after if change.type == "added" else change.before
        word = "新增组件" if change.type == "added" else "删除组件"
        cls = "diff-new" if change.type == "added" else "diff-old"
        atoms.append({
            "key": ("component", change.field or "", change.type), "label": _field_label(change.field, "component"),
            "badge": badge, "html": f'<span class="{cls}">{word} {_esc(comp)}</span>',
            "cmp": f"{change.type}:{comp}",
        })
        return atoms

    if change.category == "field":
        subs = _split_subfields(change)
        if subs:
            base_label = _field_label(change.field, "field")
            for k, bv, av in subs:
                atoms.append({
                    "key": (change.field, k), "label": f"{base_label} {_SUBFIELD_LABELS.get(k, k)}",
                    "badge": badge,
                    "html": f'<span class="diff-old">{_format_value(bv)}</span><span class="arr">→</span><span class="diff-new">{_format_value(av)}</span>',
                    "cmp": repr(av),
                })
            return atoms

    # field（未拆分）/ resource / event / 其他
    atoms.append({
        "key": (change.category, change.field or ""), "label": _field_label(change.field, change.category),
        "badge": badge,
        "html": f'<span class="diff-old">{_format_value(change.before)}</span><span class="arr">→</span><span class="diff-new">{_format_value(change.after)}</span>',
        "cmp": repr(change.after),
    })
    return atoms


def _atoms_of(changes: List[Any]) -> Tuple[Dict[Any, Dict[str, Any]], List[Any]]:
    """变更列表 → 原子行字典 + 出现顺序（排除 match 元信息）"""
    out: Dict[Any, Dict[str, Any]] = {}
    order: List[Any] = []
    for c in changes:
        if c.category == "match":
            continue
        for atom in _change_atoms(c):
            if atom["key"] not in out:
                out[atom["key"]] = atom
                order.append(atom["key"])
    return out, order


def _match_warnings(changes: List[Any]) -> List[Any]:
    return [c for c in changes if c.category == "match"]


def _node_risk(changes: List[Any]) -> str:
    risks = {c.risk for c in changes}
    if "high" in risks:
        return "high"
    if "medium" in risks:
        return "medium"
    return "low"


# ═══════════════════════════════════════
# HTML 组件渲染
# ═══════════════════════════════════════

def _breadcrumb(path: str) -> str:
    parts = str(path).split("/")
    leaf = parts[-1]
    prefix = "/".join(parts[:-1])
    prefix_html = f'<span class="crumb-dim">{_esc(prefix)}/</span>' if prefix else ""
    return f'<span class="crumb">{prefix_html}<span class="crumb-leaf">{_esc(leaf)}</span></span>'


def _badges_html(changes: List[Any]) -> str:
    _, badges = _analyze_changes(changes)
    return "".join(
        f'<span class="badge" style="border-color:{b["color"]};color:{b["color"]};'
        f'background:{b["color"]}1a">{_esc(b["label"])}</span>'
        for b in badges
    )


def _detail_rows(changes: List[Any]) -> str:
    """展开后的变更明细行"""
    atoms, order = _atoms_of(changes)
    rows = []
    for key in order:
        a = atoms[key]
        rows.append(
            f'<div class="chg-row">'
            f'<span class="badge" style="border-color:{a["badge"]["color"]};color:{a["badge"]["color"]};'
            f'background:{a["badge"]["color"]}1a">{_esc(a["badge"]["label"])}</span>'
            f'<span class="chg-label">{_esc(a["label"])}</span>'
            f'<span class="chg-diff">{a["html"]}</span>'
            f'</div>'
        )
    for c in _match_warnings(changes):
        meta = _CHANGE_META.get((c.category, c.type))
        label = meta[1] if meta else c.type
        rows.append(
            f'<div class="chg-row chg-row-warn">'
            f'<span class="badge" style="border-color:#dc2626;color:#fca5a5;background:#dc26261a">{_esc(label)}</span>'
            f'<span class="chg-label">匹配置信度 {c.confidence}，结果可能不准</span>'
            f'</div>'
        )
    return "\n".join(rows)


def _node_card(item: Dict[str, Any], expanded: bool) -> str:
    """节点摘要行 + 可折叠明细（单边修改区 / 改动一致区）"""
    changes = item["changes"]
    risk = _node_risk(changes)
    risk_dot = f'<span class="risk-dot risk-{risk}"></span>' if risk != "low" else ""
    arrow = "▼" if expanded else "▶"
    display = "block" if expanded else "none"
    n = len([c for c in changes if c.category != "match"])
    return f"""
    <div class="node-card{' node-card-risk' if risk == 'high' else ''}">
      <div class="node-head" onclick="tg(this)">
        <span class="arrow">{arrow}</span>
        {_breadcrumb(item['path'])}
        <span class="badges">{_badges_html(changes)}</span>
        {risk_dot}
        <span class="count">{n} 处</span>
      </div>
      <div class="node-body" style="display:{display}">
        {_detail_rows(changes)}
      </div>
    </div>"""


def _conflict_card(item: Dict[str, Any]) -> str:
    """真冲突卡片：字段级对齐三列视图"""
    o_atoms, o_order = _atoms_of(item["ours"])
    t_atoms, t_order = _atoms_of(item["theirs"])
    order = list(o_order) + [k for k in t_order if k not in o_atoms]

    # 一方整体删除节点而另一方有任何修改 → 全部视为碰撞
    delete_vs_modify = (("node", "deleted") in o_atoms and t_atoms) or (("node", "deleted") in t_atoms and o_atoms)

    rows = []
    collisions = 0
    for key in order:
        o, t = o_atoms.get(key), t_atoms.get(key)
        atom = o or t
        if o and t:
            status = "agree" if o["cmp"] == t["cmp"] else "collision"
        else:
            status = "ours" if o else "theirs"
        if delete_vs_modify and status != "agree":
            status = "collision"
        if status == "collision":
            collisions += 1

        cls = {"collision": "row-collision", "agree": "row-agree"}.get(status, "")
        icon = {"collision": "⚡ ", "agree": "✓ "}.get(status, "")
        badge = atom["badge"]
        label_cell = (f'<div class="fg-cell fg-label {cls}">{icon}'
                      f'<span class="badge" style="border-color:{badge["color"]};color:{badge["color"]};'
                      f'background:{badge["color"]}1a">{_esc(badge["label"])}</span>'
                      f'{_esc(atom["label"])}</div>')
        o_cell = f'<div class="fg-cell {cls}">{o["html"]}</div>' if o else f'<div class="fg-cell fg-dim {cls}">（未修改）</div>'
        t_cell = f'<div class="fg-cell {cls}">{t["html"]}</div>' if t else f'<div class="fg-cell fg-dim {cls}">（未修改）</div>'
        rows.append(label_cell + o_cell + t_cell)

    # 低置信度匹配警示 chip
    warn_chips = ""
    warns = _match_warnings(item["ours"]) + _match_warnings(item["theirs"])
    if warns:
        min_conf = min(c.confidence for c in warns)
        warn_chips = f'<span class="chip chip-warn">低置信度匹配 {min_conf}</span>'

    risk = _node_risk(item["ours"] + item["theirs"])
    risk_label = {"high": "高风险", "medium": "中风险", "low": "低风险"}[risk]

    if collisions:
        verdict = f'<div class="verdict verdict-bad">✕ {collisions} 个字段碰撞，必须人工取舍（二选一或在编辑器中重做）</div>'
    else:
        verdict = '<div class="verdict verdict-ok">✓ 双方改的是不同字段，可手动两边都保留</div>'

    return f"""
    <div class="conflict-card">
      <div class="conflict-head">
        <span class="conflict-icon">⚠️</span>
        {_breadcrumb(item['path'])}
        {warn_chips}
        <span class="chip chip-{risk}">{risk_label}</span>
      </div>
      <div class="fgrid">
        <div class="fg-head">字段</div>
        <div class="fg-head">Ours（本地）</div>
        <div class="fg-head">Theirs（分支）</div>
        {''.join(rows)}
      </div>
      {verdict}
    </div>"""


_OP_LABELS = {"deleted": "删除", "moved": "移动", "moved_and_renamed": "移动并重命名"}
_SIDE_LABELS = {"ours": "Ours（本地）", "theirs": "Theirs（分支）"}


def _tree_conflict_card(tc: Dict[str, Any]) -> str:
    op_label = _OP_LABELS.get(tc["op_type"], tc["op_type"])
    op_side = _SIDE_LABELS.get(tc["op_side"], tc["op_side"])
    other_side = _SIDE_LABELS["theirs" if tc["op_side"] == "ours" else "ours"]
    affected_html = "\n".join(_node_card(item, expanded=True) for item in tc["affected"])
    return f"""
    <div class="tree-card">
      <div class="tree-head">🌳 {op_side} <strong>{op_label}</strong>了子树 {_breadcrumb(tc['path'])}，
        但 {other_side} 修改了其内部 {len(tc['affected'])} 个节点</div>
      <div class="tree-note">这些内部修改在合并后将无处安放（或随子树换位而失效），必须人工决定取舍。</div>
      {affected_html}
    </div>"""


# ═══════════════════════════════════════
# 概览页
# ═══════════════════════════════════════

_OVERVIEW_CSS = """
  * { box-sizing: border-box; }
  body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Microsoft YaHei",sans-serif;
         background:#0b1120; color:#e2e8f0; font-size:13px; line-height:1.5; }
  .container { max-width:1280px; margin:0 auto; padding:20px; }
  h1 { margin:0 0 8px; font-size:20px; color:#f8fafc; }
  h2 { margin:28px 0 4px; font-size:15px; color:#f8fafc; display:flex; align-items:center; gap:8px; }
  .sec-note { color:#64748b; font-size:12px; margin:0 0 12px; }
  .meta { color:#64748b; font-size:12px; margin-bottom:6px; }
  .meta b { color:#94a3b8; font-weight:600; }
  .role { border-bottom:1px dotted #475569; cursor:help; }

  details.help { margin:0 0 16px; }
  details.help summary { color:#64748b; font-size:12px; cursor:pointer; user-select:none;
                         list-style:none; display:inline-block; }
  details.help summary::-webkit-details-marker { display:none; }
  details.help summary:hover { color:#94a3b8; }
  details.help[open] summary { color:#94a3b8; }
  .help-body { margin-top:8px; background:#111827; border:1px solid #1e293b; border-radius:8px;
               padding:12px 14px; font-size:12px; color:#94a3b8; line-height:1.8; max-width:920px; }
  .role-row { display:flex; gap:10px; align-items:baseline; }
  .role-name { font-weight:700; min-width:52px; font-family:ui-monospace,Consolas,monospace; }
  .role-file { color:#64748b; font-family:ui-monospace,Consolas,monospace; }
  .help-method { margin-top:8px; padding-top:8px; border-top:1px dashed #1e293b; color:#64748b; }
  .help-method b { color:#94a3b8; }

  .links { margin-bottom:20px; }
  .links a { display:inline-block; background:#1e3a5f; color:#60a5fa; padding:7px 14px; border-radius:6px;
             text-decoration:none; margin:0 8px 8px 0; font-size:12px; }
  .links a:hover { background:#2563eb; color:#fff; }

  .stat-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px; margin-bottom:8px; }
  a.stat-card { display:block; background:#111827; border:1px solid #1e293b; border-radius:8px; padding:10px;
                text-align:center; text-decoration:none; transition:border-color .15s; }
  a.stat-card:hover { border-color:#475569; }
  .stat-value { font-size:22px; font-weight:bold; margin-bottom:2px; }
  .stat-label { font-size:11px; color:#94a3b8; line-height:1.4; }

  .count-pill { font-size:11px; font-weight:600; padding:1px 8px; border-radius:10px; }
  .pill-red { background:#7f1d1d; color:#fca5a5; }
  .pill-orange { background:#92400e; color:#fbbf24; }
  .pill-green { background:#14532d; color:#86efac; }
  .pill-blue { background:#1e3a5f; color:#60a5fa; }

  .badge { font-size:10px; padding:0 5px; border-radius:3px; border:1px solid; margin-right:4px; white-space:nowrap; }
  .crumb { font-family:ui-monospace,Consolas,monospace; font-size:12px; }
  .crumb-dim { color:#64748b; }
  .crumb-leaf { color:#f8fafc; font-weight:600; }
  .mono { font-family:ui-monospace,Consolas,monospace; }
  .val-none { color:#64748b; font-style:italic; }
  .swatch { display:inline-block; width:11px; height:11px; border-radius:2px; border:1px solid #475569;
            margin-right:4px; vertical-align:-1px; }
  .diff-old { color:#fca5a5; text-decoration:line-through; text-decoration-color:rgba(252,165,165,.5); }
  .diff-new { color:#86efac; }
  .arr { color:#64748b; margin:0 6px; }

  .node-card { background:#111827; border:1px solid #1e293b; border-radius:6px; margin-bottom:6px; }
  .node-card-risk { border-left:3px solid #ef4444; }
  .node-head { display:flex; align-items:center; gap:8px; padding:7px 10px; cursor:pointer; user-select:none; }
  .node-head:hover { background:#1e293b; border-radius:6px; }
  .arrow { color:#64748b; font-size:10px; width:12px; flex-shrink:0; }
  .badges { display:flex; flex-wrap:wrap; gap:2px; margin-left:auto; }
  .risk-dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
  .risk-high { background:#ef4444; }
  .risk-medium { background:#f59e0b; }
  .count { color:#64748b; font-size:11px; white-space:nowrap; }
  .node-body { padding:2px 10px 8px 30px; border-top:1px solid #1e293b; }

  .chg-row { display:flex; align-items:baseline; gap:8px; padding:4px 0; font-size:12px; }
  .chg-row + .chg-row { border-top:1px solid rgba(30,41,59,.6); }
  .chg-label { color:#94a3b8; min-width:90px; }
  .chg-diff { flex:1; }
  .chg-row-warn .chg-label { color:#fca5a5; min-width:0; }

  .conflict-card { background:#160e0e; border:1px solid #7f1d1d; border-radius:8px; padding:12px; margin-bottom:12px; }
  .conflict-head { display:flex; align-items:center; gap:8px; margin-bottom:10px; }
  .conflict-icon { font-size:14px; }
  .chip { font-size:10px; padding:1px 6px; border-radius:3px; font-weight:600; margin-left:auto; }
  .chip-high { background:#7f1d1d; color:#fca5a5; }
  .chip-medium { background:#713f12; color:#fde047; }
  .chip-low { background:#14532d; color:#86efac; }
  .chip-warn { background:#7f1d1d; color:#fca5a5; margin-left:auto; }
  .chip-warn + .chip { margin-left:0; }

  .fgrid { display:grid; grid-template-columns:minmax(150px,200px) 1fr 1fr; border:1px solid #334155;
           border-radius:6px; overflow:hidden; font-size:12px; }
  .fg-head { background:#1e293b; color:#94a3b8; font-weight:600; padding:5px 10px; font-size:11px;
             text-transform:uppercase; letter-spacing:.5px; }
  .fg-cell { padding:6px 10px; border-top:1px solid #1e293b; display:flex; align-items:center; flex-wrap:wrap; gap:2px; }
  .fg-label { color:#e2e8f0; }
  .fg-dim { color:#475569; font-style:italic; }
  .row-collision { background:rgba(239,68,68,.12); }
  .row-agree { background:rgba(34,197,94,.08); }

  .verdict { margin-top:10px; padding:6px 10px; border-radius:6px; font-size:12px; font-weight:600; }
  .verdict-bad { background:rgba(239,68,68,.12); color:#fca5a5; border:1px solid #7f1d1d; }
  .verdict-ok { background:rgba(245,158,11,.10); color:#fde047; border:1px solid #713f12; }

  .tree-card { background:#1c1207; border:1px solid #92400e; border-radius:8px; padding:12px; margin-bottom:12px; }
  .tree-head { color:#fbbf24; font-size:13px; margin-bottom:4px; }
  .tree-head strong { color:#fde047; }
  .tree-note { color:#94a3b8; font-size:12px; margin-bottom:10px; }

  .conv-card .node-head { }
  .empty-hint { color:#64748b; padding:16px; text-align:center; background:#111827;
                border:1px dashed #1e293b; border-radius:8px; }
  .side-grid { display:flex; gap:20px; align-items:flex-start; }
  .side-col { flex:1; min-width:0; }
  .scroll-box { max-height:640px; overflow-y:auto; }
  .tips { margin-top:28px; padding:14px 16px; background:#111827; border:1px solid #1e293b;
          border-radius:8px; color:#94a3b8; font-size:12px; line-height:1.8; }
  .tips b { color:#e2e8f0; }
"""

_OVERVIEW_JS = """
function tg(h){
  var b = h.nextElementSibling, a = h.querySelector('.arrow');
  var show = b.style.display === 'none';
  b.style.display = show ? 'block' : 'none';
  a.textContent = show ? '▼' : '▶';
}
"""


def _build_overview_html(data: Dict[str, Any], ours_report_name: str,
                         theirs_report_name: str, cross_report_name: str) -> str:
    s = data["summary"]
    group = data["group"]

    # ── 树级冲突 ──
    tree_html = "\n".join(_tree_conflict_card(tc) for tc in data["tree_conflicts"])

    # ── 真冲突 ──
    conflict_html = "\n".join(_conflict_card(item) for item in data["both_modified"])
    if not data["both_modified"] and not data["tree_conflicts"]:
        conflict_html = '<div class="empty-hint">🎉 没有检测到真冲突：双方没有以不同方式修改同一节点，也没有树级冲突。可机械合并。</div>'

    # ── 改动一致（默认收起）──
    convergent_html = "\n".join(_node_card(item, expanded=False) for item in data["both_convergent"])

    # ── 单边修改（高/中风险展开，低风险收起）──
    def _side_html(items: List[Dict[str, Any]]) -> str:
        if not items:
            return '<div class="empty-hint">无</div>'
        return "\n".join(_node_card(item, expanded=_node_risk(item["changes"]) != "low") for item in items)

    ours_html = _side_html(data["only_ours"])
    theirs_html = _side_html(data["only_theirs"])

    tree_block = f"""
  <div class="section" id="sec-tree">
    <h2>🌳 树级冲突 <span class="count-pill pill-orange">{s['tree_conflicts']} 处</span></h2>
    <p class="sec-note">一方删除或移动了整棵子树，另一方却修改了子树内部的节点。按节点对碰发现不了这类冲突，需要特别注意。</p>
    {tree_html}
  </div>""" if data["tree_conflicts"] else ""

    convergent_block = f"""
  <div class="section" id="sec-convergent">
    <h2>🟩 双方改动一致 <span class="count-pill pill-green">{s['convergent_nodes']} 个节点</span></h2>
    <p class="sec-note">双方都修改了这些节点，但改成了相同结果（假冲突）。合并时任取一边即可。</p>
    {convergent_html}
  </div>""" if data["both_convergent"] else ""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>SVN 冲突概览 — {_esc(group['name'])}</title>
<style>{_OVERVIEW_CSS}</style>
</head>
<body>
<div class="container">
  <h1>🌲 SVN 冲突概览 — {_esc(group['name'])}</h1>
  <div class="meta">
    <b class="role" title="共同祖先：两边分叉前最后的共同版本（merge-left 文件），是判断“谁改了什么”的参照系">base</b> {_esc(os.path.basename(group['base']))} &nbsp;|&nbsp;
    <b class="role" title="本地：你工作区当前的内容（.working 文件）">ours</b> {_esc(os.path.basename(group['ours']))} &nbsp;|&nbsp;
    <b class="role" title="分支：svn merge 正在合入的对方版本（merge-right 文件）">theirs</b> {_esc(os.path.basename(group['theirs']))} &nbsp;|&nbsp;
    生成时间 {data['stamp']}
  </div>

  <details class="help">
    <summary>❓ base / ours / theirs 是什么？</summary>
    <div class="help-body">
      <div class="role-row"><span class="role-name" style="color:#e2e8f0;">base</span>
        <span>共同祖先 —— 两边分叉前最后的共同版本，是判断“谁改了什么”的参照系。
        <span class="role-file">（merge-left.rN 文件）</span></span></div>
      <div class="role-row"><span class="role-name" style="color:#60a5fa;">ours</span>
        <span>本地 —— 你工作区当前的内容，即执行合并的这一方。
        <span class="role-file">（.working 文件）</span></span></div>
      <div class="role-row"><span class="role-name" style="color:#34d399;">theirs</span>
        <span>分支 —— svn merge 正在合入的对方版本。
        <span class="role-file">（merge-right.rN 文件）</span></span></div>
      <div class="help-method">
        <b>分析方法</b>：分别计算 base→ours（我改了什么）和 base→theirs（对方改了什么），再按节点交叉归类——
        只有一边改过的节点可以直接采用，两边都改过的才需要人工处理。
        ours↔theirs 直接对比仅供参考：它只能看出两个终态不同，分不清是谁改的。
      </div>
    </div>
  </details>

  <div class="links">
    <a href="{ours_report_name}" target="_blank">📄 base → ours 完整报告</a>
    <a href="{theirs_report_name}" target="_blank">📄 base → theirs 完整报告</a>
    <a href="{cross_report_name}" target="_blank">📄 ours ↔ theirs 直接对比（参考）</a>
  </div>

  <div class="stat-grid">
    <a class="stat-card" href="#sec-conflict">
      <div class="stat-value" style="color:#ef4444;">{s['both_modified_nodes']}</div>
      <div class="stat-label">真冲突节点<br><small style="color:#ef4444;">双方改法不同</small></div>
    </a>
    <a class="stat-card" href="#sec-tree">
      <div class="stat-value" style="color:#fbbf24;">{s['tree_conflicts']}</div>
      <div class="stat-label">树级冲突<br><small style="color:#fbbf24;">删/移子树 vs 改内部</small></div>
    </a>
    <a class="stat-card" href="#sec-convergent">
      <div class="stat-value" style="color:#4ade80;">{s['convergent_nodes']}</div>
      <div class="stat-label">双方改动一致<br><small style="color:#4ade80;">假冲突，任取一边</small></div>
    </a>
    <a class="stat-card" href="#sec-ours">
      <div class="stat-value" style="color:#60a5fa;">{s['only_ours_nodes']}</div>
      <div class="stat-label">仅 ours 修改<br><small style="color:#60a5fa;">可安全保留</small></div>
    </a>
    <a class="stat-card" href="#sec-theirs">
      <div class="stat-value" style="color:#34d399;">{s['only_theirs_nodes']}</div>
      <div class="stat-label">仅 theirs 修改<br><small style="color:#34d399;">可安全合入</small></div>
    </a>
    <a class="stat-card" href="#sec-conflict">
      <div class="stat-value" style="color:#f59e0b;">{s['ours_high_risk']} / {s['theirs_high_risk']}</div>
      <div class="stat-label">高风险变更<br><small>ours / theirs</small></div>
    </a>
  </div>

  {tree_block}

  <div class="section" id="sec-conflict">
    <h2>🔴 真冲突区域 <span class="count-pill pill-red">{s['both_modified_nodes']} 个节点</span></h2>
    <p class="sec-note">以下节点被两边以不同方式修改过。⚡ 红色行表示同一字段被改成不同值，必须人工取舍；无碰撞行的卡片可手动两边都保留。</p>
    {conflict_html}
  </div>

  {convergent_block}

  <div class="side-grid">
    <div class="side-col section" id="sec-ours">
      <h2>🔵 仅 ours 修改 <span class="count-pill pill-blue">{s['only_ours_nodes']} 个节点</span></h2>
      <p class="sec-note">只有 ours 修改了这些节点，合入时可直接保留。点击行展开明细，高/中风险默认展开。</p>
      <div class="scroll-box">{ours_html}</div>
    </div>
    <div class="side-col section" id="sec-theirs">
      <h2>🟢 仅 theirs 修改 <span class="count-pill pill-green">{s['only_theirs_nodes']} 个节点</span></h2>
      <p class="sec-note">只有 theirs 修改了这些节点，合入时可直接采纳。点击行展开明细，高/中风险默认展开。</p>
      <div class="scroll-box">{theirs_html}</div>
    </div>
  </div>

  <div class="tips">
    <b>💡 使用建议</b><br>
    1. 优先处理<b style="color:#fbbf24;">树级冲突</b>和<b style="color:#fca5a5;">真冲突区域</b>，这两类必须人工决定取舍。<br>
    2. 真冲突卡片里只看 ⚡ 红色行：那是同一字段被改成不同值的硬碰撞；没有红色行的卡片可以两边修改都保留。<br>
    3. <b style="color:#86efac;">双方改动一致</b>的节点是假冲突，任取一边即可。<br>
    4. 点击上方链接查看完整树形报告，可精确定位字段级差异。
  </div>
</div>
<script>{_OVERVIEW_JS}</script>
</body>
</html>
"""


def generate_reports(data: Dict[str, Any], out_dir: str, progress=print) -> str:
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
    progress(f"   ✓ base → ours:   {ours_path}")
    progress(f"   ✓ base → theirs: {theirs_path}")
    progress(f"   ✓ ours ↔ theirs: {cross_path}")

    # 概览报告
    overview_name = f"{safe}_conflict_overview_{stamp}.html"
    overview_path = os.path.join(out_dir, overview_name)
    html_text = _build_overview_html(data, ours_name, theirs_name, cross_name)
    with open(overview_path, "w", encoding="utf-8") as f:
        f.write(html_text)
    progress(f"   ✓ 冲突概览:      {overview_path}")

    return overview_path


# ═══════════════════════════════════════
# 主入口
# ═══════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="SVN prefab 冲突快速分析")
    parser.add_argument("target", nargs="?", help=".working 文件路径，或目录路径（配合 --scan）")
    parser.add_argument("--scan", action="store_true", help="扫描目录内所有冲突组")
    parser.add_argument("--out-dir", default=os.path.join(PROJECT_ROOT, "reports", "svn_conflict"), help="输出目录（默认脚本所在目录的 reports/svn_conflict/）")
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
        try:
            groups = [find_group_by_working(args.target)]
        except ValueError as e:
            print(f"❌ {e}")
            sys.exit(2)

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
