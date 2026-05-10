#!/usr/bin/env python3
import html
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from change_model import Change, DiffResult
from prefab_parser import parse_prefab
from prefab_model import PrefabDocument, PrefabNode


_CHANGE_META: Dict[Tuple[str, str], Tuple[str, str, str]] = {
    ("node", "added"): ("chg-added", "新增", "#22c55e"),
    ("node", "deleted"): ("chg-deleted", "删除", "#ef4444"),
    ("node", "moved"): ("chg-moved", "移动", "#3b82f6"),
    ("node", "renamed"): ("chg-renamed", "重命名", "#a855f7"),
    ("node", "moved_and_renamed"): ("chg-moved-renamed", "移动+重命名", "#6366f1"),
    ("node", "child_order_changed"): ("chg-order", "子节点顺序", "#60a5fa"),
    ("field", "changed"): ("chg-field", "字段", "#f59e0b"),
    ("resource", "changed"): ("chg-resource", "资源", "#06b6d4"),
    ("event", "changed"): ("chg-event", "事件", "#ec4899"),
    ("component", "added"): ("chg-component", "组件新增", "#f97316"),
    ("component", "deleted"): ("chg-component", "组件删除", "#f97316"),
    ("component", "order_changed"): ("chg-component", "组件顺序", "#f97316"),
    ("component", "changed"): ("chg-component", "组件变化", "#f97316"),
    ("match", "uncertain"): ("chg-uncertain", "低置信度", "#dc2626"),
    ("match", "ambiguous"): ("chg-uncertain", "多候选", "#dc2626"),
}

_CHANGE_PRIORITY = [
    ("match", "uncertain"), ("match", "ambiguous"),
    ("node", "deleted"), ("node", "added"),
    ("node", "moved_and_renamed"), ("node", "moved"), ("node", "renamed"),
    ("event", "changed"),
    ("component", "added"), ("component", "deleted"),
    ("component", "order_changed"), ("component", "changed"),
    ("resource", "changed"), ("field", "changed"), ("node", "child_order_changed"),
]


def write_html_report(p_result: DiffResult, p_file_path: str) -> None:
    t_before_doc = parse_prefab(p_result.before_file)
    t_after_doc = parse_prefab(p_result.after_file)
    t_html = render_html(p_result, t_before_doc, t_after_doc)
    t_dir = os.path.dirname(p_file_path)
    if t_dir and not os.path.isdir(t_dir):
        os.makedirs(t_dir)
    with open(p_file_path, "w", encoding="utf-8") as f:
        f.write(t_html)


def render_html(p_result, p_before_doc, p_after_doc):
    t_before_idx = _build_path_index(p_result.changes, "before")
    t_after_idx = _build_path_index(p_result.changes, "after")
    t_before_match_idx = _build_match_index(p_result.matches, "before")
    t_after_match_idx = _build_match_index(p_result.matches, "after")
    t_before_tree = _render_tree(p_before_doc.root_nodes, t_before_idx, t_before_match_idx, "before")
    t_after_tree = _render_tree(p_after_doc.root_nodes, t_after_idx, t_after_match_idx, "after")
    t_stats = _compute_stats(p_result)
    t_changes_raw = _serialize_changes(p_result.changes)
    t_changes_json = json.dumps(t_changes_raw, ensure_ascii=False)
    t_changes_json = t_changes_json.replace("</script>", "<\\/script>")
    t_changes_json = t_changes_json.replace("%", "%%")
    t_matches_json = json.dumps(p_result.matches, ensure_ascii=False)
    t_matches_json = t_matches_json.replace("</script>", "<\\/script>")
    t_matches_json = t_matches_json.replace("%", "%%")
    t_legend = _render_legend()
    t_template = _load_template("tree_report.html")

    return t_template % {
        "title": "PfbDiff 树形对比报告",
        "before_file": _e(os.path.basename(p_result.before_file)),
        "after_file": _e(os.path.basename(p_result.after_file)),
        "before_path": _e(os.path.abspath(p_result.before_file)),
        "after_path": _e(os.path.abspath(p_result.after_file)),
        "before_tree": t_before_tree,
        "after_tree": t_after_tree,
        "legend": t_legend,
        "stats_added": t_stats["added"],
        "stats_deleted": t_stats["deleted"],
        "stats_moved": t_stats["moved"],
        "stats_renamed": t_stats["renamed"],
        "stats_field": t_stats["field"],
        "stats_resource": t_stats["resource"],
        "stats_event": t_stats["event"],
        "stats_component": t_stats["component"],
        "stats_uncertain": t_stats["uncertain"],
        "changes_json": t_changes_json,
        "matches_json": t_matches_json,
    }


def _build_path_index(p_changes: List[Change], p_side: str) -> Dict[str, List[Change]]:
    t_idx: Dict[str, List[Change]] = {}
    for c in p_changes:
        if c.category == "warning":
            continue
        t_path = c.before_internal_path if p_side == "before" else c.after_internal_path
        if not t_path:
            t_path = c.before_path if p_side == "before" else c.after_path
        if t_path:
            t_idx.setdefault(t_path, []).append(c)
    return t_idx


def _build_match_index(p_matches: List[Dict[str, Any]], p_side: str) -> Dict[str, Dict[str, Any]]:
    t_idx: Dict[str, Dict[str, Any]] = {}
    for m in p_matches:
        t_path = m.get("before_internal_path" if p_side == "before" else "after_internal_path")
        if t_path:
            t_idx[t_path] = m
    return t_idx


def _render_tree(p_nodes: List[PrefabNode], p_idx: Dict[str, List[Change]], p_match_idx: Dict[str, Dict[str, Any]], p_side: str) -> str:
    if not p_nodes:
        return '<div class="empty-tree">无节点</div>'
    t_items = []
    for node in p_nodes:
        t_items.append(_render_node(node, p_idx, p_match_idx, p_side, 0))
    return "".join(t_items)


def _render_node(p_node: PrefabNode, p_idx: Dict[str, List[Change]], p_match_idx: Dict[str, Dict[str, Any]], p_side: str, p_depth: int) -> str:
    if p_node.internal_path in p_idx:
        t_changes = p_idx[p_node.internal_path]
    elif p_node.path in p_idx:
        t_changes = p_idx[p_node.path]
    else:
        t_changes = []
    t_row_cls, t_badges = _analyze_changes(t_changes)
    t_has_children = bool(p_node.children)
    t_toggle = "▼" if t_has_children else " "
    t_indent = p_depth * 18

    t_match_attrs = ""
    t_match = p_match_idx.get(p_node.internal_path) or p_match_idx.get(p_node.path)
    if t_match:
        t_conf = t_match.get("confidence", 0)
        t_status = t_match.get("status", "")
        t_reasons = t_match.get("reasons", [])
        t_match_attrs = ' data-match-status="%s" data-match-confidence="%s" data-match-reasons="%s"' % (
            t_status, t_conf, _e(",".join(t_reasons[:3]))
        )

    t_comp_pills = "".join(
        '<span class="comp-pill">%s</span>' % _e(t)
        for t in p_node.component_types()
    )

    t_badge_html = "".join(
        '<span class="badge" style="background:%s;color:#fff">%s</span>' % (t["color"], _e(t["label"]))
        for t in t_badges
    )

    t_children_html = ""
    if t_has_children:
        t_child_items = []
        for child in p_node.children:
            t_child_items.append(_render_node(child, p_idx, p_match_idx, p_side, p_depth + 1))
        t_children_html = '<div class="children">%s</div>' % "".join(t_child_items)

    return (
        '<div class="tree-node">'
        '<div class="node-row %(cls)s" style="padding-left:%(indent)spx" '
        'data-path="%(path)s" data-internal-path="%(internal_path)s" data-side="%(side)s" data-has-children="%(has_children)s" '
        '%(match_attrs)s'
        'onclick="onNodeClick(this)">'
        '<span class="toggle" onclick="event.stopPropagation();toggleNode(this)">%(toggle)s</span>'
        '<span class="node-name">%(name)s</span>'
        '%(comp_pills)s'
        '%(badges)s'
        '</div>'
        '%(children)s'
        '</div>'
    ) % {
        "cls": t_row_cls,
        "indent": t_indent,
        "path": _e(p_node.path),
        "internal_path": _e(p_node.internal_path),
        "side": p_side,
        "has_children": "1" if t_has_children else "0",
        "match_attrs": t_match_attrs,
        "toggle": t_toggle,
        "name": _e(p_node.name),
        "comp_pills": t_comp_pills,
        "badges": t_badge_html,
        "children": t_children_html,
    }


def _analyze_changes(p_changes: List[Change]) -> Tuple[str, List[Dict[str, str]]]:
    if not p_changes:
        return "", []

    t_sorted = sorted(p_changes, key=lambda c: _change_priority_key(c))
    t_main = t_sorted[0] if t_sorted else None
    t_cls = ""
    if t_main:
        t_meta = _CHANGE_META.get((t_main.category, t_main.type))
        if t_meta:
            t_cls = t_meta[0]

    t_badges = []
    t_seen = set()
    for c in t_sorted:
        t_key = (c.category, c.type)
        if t_key in t_seen:
            continue
        t_seen.add(t_key)
        t_meta = _CHANGE_META.get(t_key)
        if t_meta:
            t_badges.append({"label": t_meta[1], "color": t_meta[2], "css": t_meta[0]})

    return t_cls, t_badges


def _change_priority_key(p_change: Change) -> int:
    t_key = (p_change.category, p_change.type)
    try:
        return _CHANGE_PRIORITY.index(t_key)
    except ValueError:
        return 999


def _compute_stats(p_result: DiffResult) -> Dict[str, int]:
    t_s = {"added":0,"deleted":0,"moved":0,"renamed":0,"field":0,"resource":0,"event":0,"component":0,"uncertain":0}
    for c in p_result.changes:
        if c.category == "warning":
            continue
        if c.category == "node" and c.type in t_s:
            t_s[c.type] = t_s.get(c.type, 0) + 1
        elif c.category in ("field","resource","event"):
            t_s[c.category] = t_s.get(c.category, 0) + 1
        elif c.category == "component":
            t_s["component"] = t_s.get("component", 0) + 1
        elif c.category == "match" and c.type in ("uncertain","ambiguous"):
            t_s["uncertain"] = t_s.get("uncertain", 0) + 1
    return t_s


def _serialize_changes(p_changes: List[Change]) -> List[Dict[str, Any]]:
    t_out = []
    for c in p_changes:
        if c.category == "warning":
            continue
        t_out.append({
            "category": c.category,
            "type": c.type,
            "risk": c.risk,
            "beforePath": c.before_path,
            "afterPath": c.after_path,
            "beforeInternalPath": c.before_internal_path,
            "afterInternalPath": c.after_internal_path,
            "field": c.field,
            "before": c.before,
            "after": c.after,
            "confidence": c.confidence,
            "details": c.details,
        })
    return t_out


def _render_legend() -> str:
    t_items = []
    t_seen = set()
    for t_key in _CHANGE_PRIORITY:
        if t_key in t_seen:
            continue
        t_seen.add(t_key)
        t_meta = _CHANGE_META.get(t_key)
        if not t_meta:
            continue
        t_items.append(
            '<span class="legend-item"><span class="legend-dot" style="background:%s"></span>%s</span>' % (t_meta[2], _e(t_meta[1]))
        )
    return "".join(t_items)


def _e(p_value: Any) -> str:
    return html.escape("" if p_value is None else str(p_value), quote=True)



def _load_template(p_name: str) -> str:
    t_dir = os.path.dirname(os.path.abspath(__file__))
    if hasattr(sys, "_MEIPASS"):
        t_dir = sys._MEIPASS
    t_path = os.path.join(t_dir, "templates", p_name)
    with open(t_path, "r", encoding="utf-8") as f:
        return f.read()

