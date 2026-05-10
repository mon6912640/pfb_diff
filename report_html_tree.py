#!/usr/bin/env python3
import html
import json
import os
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
    t_before_tree = _render_tree(p_before_doc.root_nodes, t_before_idx, "before")
    t_after_tree = _render_tree(p_after_doc.root_nodes, t_after_idx, "after")
    t_stats = _compute_stats(p_result)
    t_changes_raw = _serialize_changes(p_result.changes)
    t_changes_json = json.dumps(t_changes_raw, ensure_ascii=False)
    t_changes_json = t_changes_json.replace("</script>", "<\\/script>")
    t_changes_json = t_changes_json.replace("%", "%%")
    t_legend = _render_legend()

    return PAGE_TEMPLATE % {
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


def _render_tree(p_nodes: List[PrefabNode], p_idx: Dict[str, List[Change]], p_side: str) -> str:
    if not p_nodes:
        return '<div class="empty-tree">无节点</div>'
    t_items = []
    for node in p_nodes:
        t_items.append(_render_node(node, p_idx, p_side, 0))
    return "".join(t_items)


def _render_node(p_node: PrefabNode, p_idx: Dict[str, List[Change]], p_side: str, p_depth: int) -> str:
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
            t_child_items.append(_render_node(child, p_idx, p_side, p_depth + 1))
        t_children_html = '<div class="children">%s</div>' % "".join(t_child_items)

    return (
        '<div class="tree-node">'
        '<div class="node-row %(cls)s" style="padding-left:%(indent)spx" '
        'data-path="%(path)s" data-internal-path="%(internal_path)s" data-side="%(side)s" data-has-children="%(has_children)s" '
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


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>%(title)s</title>
<style>
* { box-sizing: border-box; }
body {
    margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Microsoft YaHei", sans-serif;
    background: #0b1120; color: #e2e8f0; font-size: 13px;
    display: flex; flex-direction: column; height: 100vh; overflow: hidden;
}
a { color: #60a5fa; }

/* Header */
.header {
    flex-shrink: 0; padding: 12px 16px; background: #0f172a;
    border-bottom: 1px solid #1e293b; display: flex; align-items: center; justify-content: space-between;
}
.header h1 { margin: 0; font-size: 16px; font-weight: 600; color: #f8fafc; }
.header .files { color: #94a3b8; font-size: 12px; }
.header .files span { margin: 0 6px; color: #475569; }
.conf-btn {
    background: #1e293b; border: 1px solid #334155; color: #94a3b8;
    padding: 4px 10px; border-radius: 4px; font-size: 12px; cursor: pointer;
}
.conf-btn:hover { background: #334155; color: #fff; }

/* Stats bar */
.stats-bar {
    flex-shrink: 0; display: flex; gap: 8px; padding: 8px 16px; background: #0f172a;
    border-bottom: 1px solid #1e293b; overflow-x: auto;
}
.stat {
    background: #1e293b; border: 1px solid #334155; border-radius: 6px;
    padding: 4px 10px; font-size: 12px; white-space: nowrap;
}
.stat b { color: #f8fafc; margin-right: 4px; }

/* Legend */
.legend-bar {
    flex-shrink: 0; padding: 6px 16px; background: #0f172a;
    border-bottom: 1px solid #1e293b; display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center;
}
.legend-item { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: #cbd5e1; user-select: none; }
.legend-item:hover { color: #fff; }
.legend-dot { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }

/* Tree area */
.tree-area {
    flex: 1; min-height: 0; display: flex; gap: 12px; padding: 12px 16px;
}
.tree-panel {
    flex: 1; min-width: 0; background: #111827; border: 1px solid #1e293b;
    border-radius: 8px; overflow: auto; padding: 10px 12px;
}
.panel-title {
    font-size: 12px; font-weight: 600; color: #94a3b8; text-transform: uppercase;
    letter-spacing: 0.5px; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid #1e293b;
    position: sticky; top: 0; background: #111827; z-index: 10;
}

/* Tree node */
.node-row {
    display: flex; align-items: center; padding: 3px 6px;
    border-left: 3px solid transparent; border-radius: 4px; margin: 1px 0;
    cursor: pointer; transition: background 0.12s; min-height: 26px;
}
.node-row:hover { background: #1e293b; }
.toggle {
    display: inline-block; width: 14px; text-align: center; font-size: 10px;
    color: #64748b; cursor: pointer; margin-right: 4px; user-select: none;
}
.node-name { font-weight: 500; color: #f1f5f9; margin-right: 6px; white-space: nowrap; }
.comp-pill {
    display: inline-block; font-size: 10px; padding: 0px 4px; border-radius: 3px;
    background: #334155; color: #94a3b8; margin-right: 4px; white-space: nowrap;
}
.badge {
    display: inline-block; font-size: 10px; padding: 1px 5px; border-radius: 3px;
    margin-left: 3px; font-weight: 600; white-space: nowrap;
}

/* Change colors on rows */
.node-row.chg-uncertain { border-left-color: #dc2626; background: rgba(220,38,38,0.12); }
.node-row.chg-deleted    { border-left-color: #ef4444; background: rgba(239,68,68,0.10); }
.node-row.chg-added      { border-left-color: #22c55e; background: rgba(34,197,94,0.10); }
.node-row.chg-moved-renamed { border-left-color: #6366f1; background: rgba(99,102,241,0.10); }
.node-row.chg-moved      { border-left-color: #3b82f6; background: rgba(59,130,246,0.10); }
.node-row.chg-renamed    { border-left-color: #a855f7; background: rgba(168,85,247,0.10); }
.node-row.chg-event      { border-left-color: #ec4899; background: rgba(236,72,153,0.10); }
.node-row.chg-component  { border-left-color: #f97316; background: rgba(249,115,22,0.10); }
.node-row.chg-resource   { border-left-color: #06b6d4; background: rgba(6,182,212,0.10); }
.node-row.chg-field      { border-left-color: #f59e0b; background: rgba(245,158,11,0.10); }
.node-row.chg-order      { border-left-color: #60a5fa; background: rgba(96,165,250,0.10); }

/* Dim unchanged nodes slightly */
.node-row:not([class*="chg-"]) .node-name { color: #94a3b8; }

/* Empty tree */
.empty-tree { color: #64748b; font-style: italic; padding: 20px; text-align: center; }

/* Detail panel */
.detail-panel {
    flex-shrink: 0; height: 380px; background: #0f172a; border-top: 1px solid #1e293b;
    overflow: auto; padding: 10px 16px; font-size: 12px;
}
.detail-panel .placeholder { color: #64748b; text-align: center; padding-top: 60px; }
.detail-item {
    background: #111827; border: 1px solid #1e293b; border-radius: 6px;
    padding: 8px 10px; margin-bottom: 8px;
}
.detail-item .detail-header {
    display: flex; align-items: center; gap: 8px; margin-bottom: 6px;
}
.detail-item .risk-tag {
    font-size: 10px; padding: 1px 5px; border-radius: 3px; font-weight: 600;
}
.risk-high { background: #7f1d1d; color: #fca5a5; }
.risk-medium { background: #713f12; color: #fde047; }
.risk-low { background: #14532d; color: #86efac; }
.detail-item .type-label { font-weight: 600; color: #f8fafc; }
.detail-item .field-path { color: #94a3b8; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.detail-item pre {
    margin: 6px 0 0; background: #0b1120; border: 1px solid #1e293b; border-radius: 4px;
    padding: 6px 8px; overflow: auto; color: #cbd5e1; font-size: 11px; line-height: 1.4;
}
.detail-item .path-info { color: #64748b; font-size: 11px; margin-top: 4px; }

/* Modal */
.modal-overlay {
    display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.6); z-index: 200; align-items: center; justify-content: center;
}
.modal-overlay.active { display: flex; }
.modal-box {
    background: #1e293b; border: 1px solid #334155; border-radius: 10px;
    width: 90%%; max-width: 640px; max-height: 80vh; display: flex; flex-direction: column;
    box-shadow: 0 20px 50px rgba(0,0,0,0.5);
}
.modal-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 18px; border-bottom: 1px solid #334155; flex-shrink: 0;
}
.modal-header h2 { margin: 0; font-size: 15px; color: #f8fafc; }
.modal-close {
    background: transparent; border: none; color: #94a3b8; font-size: 16px;
    cursor: pointer; padding: 0; width: 28px; height: 28px; border-radius: 4px; line-height: 1;
}
.modal-close:hover { background: #334155; color: #fff; }
.modal-body {
    padding: 16px 18px; overflow: auto; font-size: 12px; line-height: 1.7; color: #cbd5e1;
}
.modal-body h3 { margin: 14px 0 8px; font-size: 13px; color: #f8fafc; }
.modal-body p { margin: 6px 0; }
.modal-body ul, .modal-body ol { margin: 6px 0; padding-left: 18px; color: #cbd5e1; }
.modal-body li { margin: 3px 0; }
.modal-body code { background: #0f172a; padding: 1px 4px; border-radius: 3px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 11px; color: #86efac; }
.modal-body table { width: 100%%; border-collapse: collapse; margin: 8px 0; font-size: 11px; }
.modal-body th, .modal-body td { border: 1px solid #334155; padding: 5px 8px; text-align: left; }
.modal-body th { background: #0f172a; color: #94a3b8; font-weight: 600; }
.modal-body td { background: #111827; }
.modal-body .score-tag { display: inline-block; padding: 1px 5px; border-radius: 3px; font-size: 10px; font-weight: 600; margin-right: 4px; }
.tag-confirmed { background: #14532d; color: #86efac; }
.tag-probable { background: #713f12; color: #fde047; }
.tag-uncertain { background: #7f1d1d; color: #fca5a5; }
.tag-unmatched { background: #334155; color: #94a3b8; }

/* JSON Diff */
.json-diff { display: flex; gap: 8px; margin-top: 6px; }
.json-diff-col { flex: 1; min-width: 0; background: #0b1120; border: 1px solid #1e293b; border-radius: 4px; padding: 6px; }
.json-diff-title { font-size: 10px; color: #64748b; margin-bottom: 4px; font-weight: 600; }
.diff-line { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 11px; padding: 1px 4px; white-space: pre-wrap; word-break: break-all; line-height: 1.5; }
.diff-same { color: #cbd5e1; }
.diff-del { background: rgba(239,68,68,0.12); color: #fca5a5; }
.diff-add { background: rgba(34,197,94,0.12); color: #86efac; }
.diff-mod { background: rgba(245,158,11,0.12); color: #fde047; }
.diff-simple { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; padding: 8px; background: #0b1120; border: 1px solid #1e293b; border-radius: 4px; margin-top: 6px; }
.struct-diff { background: #0b1120; border: 1px solid #1e293b; border-radius: 4px; padding: 6px; margin-top: 6px; }
.diff-old { color: #fca5a5; margin-right: 6px; }
.diff-new { color: #86efac; }
.diff-arrow { color: #94a3b8; margin: 0 6px; }

/* Scrollbar */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #475569; }
</style>
</head>
<body>
<div class="header">
    <h1>🌲 PfbDiff 树形对比报告</h1>
    <div style="display:flex;align-items:center;gap:10px">
        <button class="conf-btn" onclick="openModal()">📖 置信度说明</button>
        <div class="files">
            <span>%(before_file)s</span>
            <span>→</span>
            <span>%(after_file)s</span>
        </div>
    </div>
</div>

<div class="stats-bar">
    <div class="stat"><b>%(stats_added)s</b>新增</div>
    <div class="stat"><b>%(stats_deleted)s</b>删除</div>
    <div class="stat"><b>%(stats_moved)s</b>移动</div>
    <div class="stat"><b>%(stats_renamed)s</b>重命名</div>
    <div class="stat"><b>%(stats_field)s</b>字段</div>
    <div class="stat"><b>%(stats_resource)s</b>资源</div>
    <div class="stat"><b>%(stats_event)s</b>事件</div>
    <div class="stat"><b>%(stats_component)s</b>组件</div>
    <div class="stat"><b>%(stats_uncertain)s</b>低置信度</div>
</div>

<div class="legend-bar">
    %(legend)s
</div>

<div class="tree-area">
    <div class="tree-panel">
        <div class="panel-title">⬅ Before（旧版本）<span style="color:#64748b;font-size:11px;font-weight:400;text-transform:none;letter-spacing:0;margin-left:8px;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-block;vertical-align:middle;" title="%(before_path)s">%(before_path)s</span></div>
        %(before_tree)s
    </div>
    <div class="tree-panel">
        <div class="panel-title">➡ After（新版本）<span style="color:#64748b;font-size:11px;font-weight:400;text-transform:none;letter-spacing:0;margin-left:8px;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-block;vertical-align:middle;" title="%(after_path)s">%(after_path)s</span></div>
        %(after_tree)s
    </div>
</div>

<div class="detail-panel" id="detailPanel">
    <div class="placeholder">点击左侧或右侧树中有颜色标记的节点，查看详细变化信息</div>
</div>

<div class="modal-overlay" id="confidenceModal" onclick="closeModal(event)">
<div class="modal-box" onclick="event.stopPropagation()">
<div class="modal-header">
    <h2>📖 置信度说明</h2>
    <button class="modal-close" onclick="closeModal()">✕</button>
</div>
<div class="modal-body">
    <p><b>置信度</b>表示工具判断「before 和 after 中两个节点是否为同一个节点」的量化把握程度（0 ~ 100）。</p>
    <p>分数不是「相似度」，而是综合了节点名称、组件结构、视觉属性、行为特征和上下文位置后的加权评分。</p>

    <h3>评分维度</h3>
    <table>
        <tr><th>维度</th><th>匹配条件</th><th>加分</th></tr>
        <tr><td>名称</td><td>节点名相同</td><td>+12</td></tr>
        <tr><td>名称</td><td>低信息名（bg/label/icon 等）</td><td>-4</td></tr>
        <tr><td>结构</td><td>structure_hash 完全相同</td><td>+18</td></tr>
        <tr><td>结构</td><td>组件类型重叠（Jaccard）</td><td>最多 +18</td></tr>
        <tr><td>结构</td><td>子节点名称重叠（Jaccard）</td><td>最多 +8</td></tr>
        <tr><td>视觉</td><td>visual_hash 完全相同</td><td>+20</td></tr>
        <tr><td>视觉</td><td>资源 uuid 重叠（Jaccard）</td><td>最多 +18</td></tr>
        <tr><td>视觉</td><td>Label 文本重叠（Jaccard）</td><td>最多 +14</td></tr>
        <tr><td>行为</td><td>behavior_hash 完全相同</td><td>+22</td></tr>
        <tr><td>行为</td><td>脚本类型重叠（Jaccard）</td><td>最多 +18</td></tr>
        <tr><td>行为</td><td>事件 handler 重叠（Jaccard）</td><td>最多 +18</td></tr>
        <tr><td>上下文</td><td>父路径相同</td><td>+8</td></tr>
        <tr><td>上下文</td><td>完整路径相同</td><td>+8</td></tr>
        <tr><td>上下文</td><td>兄弟下标相同</td><td>+4</td></tr>
        <tr><td>惩罚</td><td>无组件 + 低信息名称</td><td>-18</td></tr>
    </table>

    <h3>分级标准</h3>
    <table>
        <tr><th>分数区间</th><th>状态</th><th>含义</th></tr>
        <tr><td><span class="score-tag tag-confirmed">&gt;= 92</span></td><td>confirmed</td><td>高置信匹配，直接视为同一节点进入 diff</td></tr>
        <tr><td><span class="score-tag tag-probable">74 ~ 91</span></td><td>probable</td><td>大概率是同一节点，进入 diff，报告中展示置信度</td></tr>
        <tr><td><span class="score-tag tag-uncertain">58 ~ 73</span></td><td>uncertain</td><td>不确定，不自动视为同一节点，进入低置信度列表</td></tr>
        <tr><td><span class="score-tag tag-unmatched">&lt; 58</span></td><td>unmatched</td><td>视为新增或删除</td></tr>
    </table>

    <h3>多候选（Ambiguous）</h3>
    <p>当最高分与第二名差距 &lt;= 4 分时，即使总分达到 confirmed/probable，也会被标记为 <b>ambiguous</b>（多候选）。</p>
    <p>这表示工具发现了多个"equally likely"的匹配对象，必须由人工判断哪个才是真正的对应节点。</p>

    <h3>低信息节点</h3>
    <p>名称属于以下名单的节点被视为低信息节点，名称权重会被降低：</p>
    <p><code>bg, icon, label, title, num, txt, text, node, con, item, btn</code></p>
    <p>这些节点通常数量多、特征少，容易互相错配。工具会提高资源 uuid、组件结构和父子关系在评分中的权重来辅助消歧。</p>

    <h3>为什么需要置信度？</h3>
    <p>普通文本 diff 只看路径，会把「移动节点」误报为「删除 + 新增」。PfbDiff 用指纹匹配来识别同一节点，但如果没有置信度机制，当两个 prefab 存在大量相似节点时（如列表中的多个 Item），很容易把 A 错配成 B，导致真正的变化被掩盖。</p>
    <p>置信度机制把这种风险量化出来：<b>不敢确定的就告诉用户，让用户做最终判断。</b></p>

    <h3>低置信度在报告中如何识别？</h3>
    <p>在树形对比报告中，低置信度节点有以下特征：</p>
    <ul>
        <li>节点行左侧边框为 <b>深红色（#dc2626）</b></li>
        <li>Badge 标签显示「<b>低置信度</b>」或「<b>多候选</b>」</li>
        <li>点击节点后，详情面板显示 <code>置信度: 62</code> 之类的分数</li>
    </ul>

    <h3>低置信度的风险分级</h3>
    <table>
        <tr><th>节点特征</th><th>风险等级</th><th>说明</th></tr>
        <tr><td>低置信度 + <b>包含脚本或事件</b></td><td><span class="score-tag tag-uncertain">高风险</span></td><td>错配可能掩盖业务逻辑变化，必须人工确认</td></tr>
        <tr><td>低置信度 + 纯 UI 展示节点</td><td><span class="score-tag tag-probable">中风险</span></td><td>视觉可能错位，但不会影响代码逻辑</td></tr>
    </table>

    <h3>看到低置信度时应该怎么做？</h3>
    <ol>
        <li><b>点击节点</b>查看详情面板，看置信度分数和匹配依据（如 <code>same_name</code>、<code>resource_overlap</code>）</li>
        <li><b>对比左右两栏</b>该节点的路径、组件、资源，判断工具配得对不对</li>
        <li><b>如果配错了</b>：在人工合并时忽略工具的匹配结论，按你自己的判断处理</li>
        <li><b>如果配对了</b>：可以忽略这个警告，继续审查其他变化</li>
    </ol>

    <h3>一句话总结</h3>
    <p><b>低置信度 = 工具在「举手投降」。</b>它发现了一些相似特征，但不敢打包票说这是同一个节点。深红色就是它的求救信号——请你来做最终判断，避免错配导致真正变化被掩盖。</p>
</div>
</div>
</div>

<script>
const ALL_CHANGES = %(changes_json)s;

function toggleNode(el) {
    const row = el.closest('.node-row');
    const node = row.parentElement;
    const children = node.querySelector(':scope > .children');
    if (!children) return;
    if (children.style.display === 'none') {
        children.style.display = 'block';
        el.textContent = '▼';
    } else {
        children.style.display = 'none';
        el.textContent = '▶';
    }
}

function onNodeClick(row) {
    const internalPath = row.dataset.internalPath;
    const side = row.dataset.side;
    const panel = document.getElementById('detailPanel');

    const related = ALL_CHANGES.filter(function(c) {
        if (side === 'before') return c.beforeInternalPath === internalPath;
        return c.afterInternalPath === internalPath;
    });

    if (related.length === 0) {
        panel.innerHTML = '<div class="placeholder">该节点无记录的变化（可能是父节点的子节点顺序变化影响了显示）</div>';
        return;
    }

    const htmlParts = related.map(function(c) {
        const riskClass = c.risk === 'high' ? 'risk-high' : (c.risk === 'medium' ? 'risk-medium' : 'risk-low');
        const riskText = c.risk === 'high' ? '高' : (c.risk === 'medium' ? '中' : '低');
        const typeText = _typeText(c);
        let fieldHtml = '';
        if (c.field) {
            fieldHtml = '<div class="field-path">' + _esc(c.field) + '</div>';
        }
        let valueDiffHtml = renderValueDiff(c.before, c.after);
        let pathHtml = '';
        if (c.beforePath && c.afterPath && c.beforePath !== c.afterPath) {
            pathHtml = '<div class="path-info">' + _esc(c.beforePath) + ' → ' + _esc(c.afterPath) + '</div>';
        } else if (c.beforePath || c.afterPath) {
            pathHtml = '<div class="path-info">' + _esc(c.beforePath || c.afterPath) + '</div>';
        }
        return '<div class="detail-item">' +
            '<div class="detail-header">' +
                '<span class="risk-tag ' + riskClass + '">' + riskText + '</span>' +
                '<span class="type-label">' + _esc(typeText) + '</span>' +
            '</div>' +
            fieldHtml + pathHtml + valueDiffHtml +
        '</div>';
    });

    const sharedConfidence = related.length > 0 && related[0].confidence && related[0].confidence < 100
        ? related[0].confidence : 0;
    let confidenceColor = '#94a3b8';
    if (sharedConfidence >= 92) confidenceColor = '#86efac';
    else if (sharedConfidence >= 74) confidenceColor = '#fde047';
    else if (sharedConfidence >= 58) confidenceColor = '#fca5a5';
    const groupHeader = sharedConfidence
        ? '<div style="color:' + confidenceColor + ';font-size:11px;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid #1e293b;">节点匹配置信度: ' + sharedConfidence + '</div>'
        : '';
    panel.innerHTML = groupHeader + htmlParts.join('');
}

function _typeText(c) {
    const map = {
        'added':'新增节点', 'deleted':'删除节点', 'moved':'节点移动',
        'renamed':'节点重命名', 'moved_and_renamed':'移动并重命名',
        'child_order_changed':'子节点顺序变化', 'changed':'字段/属性变化',
        'order_changed':'组件顺序变化', 'uncertain':'低置信度匹配',
        'ambiguous':'多候选匹配'
    };
    if (c.category === 'node') return map[c.type] || c.type;
    if (c.category === 'field') return '字段变化';
    if (c.category === 'resource') return '资源引用变化';
    if (c.category === 'event') return '事件绑定变化';
    if (c.category === 'component') return '组件变化';
    if (c.category === 'match') return '匹配问题';
    return c.type;
}

function renderValueDiff(before, after) {
    if (before === undefined && after === undefined) return '';
    if (before === null && after === null) return '';
    const bType = typeof before;
    const aType = typeof after;
    if ((bType !== 'object' || before === null) && (aType !== 'object' || after === null)) {
        return '<div class="diff-simple"><span class="diff-old">' + _esc(String(before)) + '</span><span class="diff-arrow">→</span><span class="diff-new">' + _esc(String(after)) + '</span></div>';
    }
    return renderStructuredDiff(before, after);
}

function renderStructuredDiff(before, after, depth, seen) {
    depth = depth || 0;
    if (depth > 5) return '<div class="diff-simple" style="color:#64748b">[结构过深，已折叠]</div>';
    seen = seen || {before: new WeakSet(), after: new WeakSet()};
    if (before !== null && typeof before === 'object') {
        if (seen.before.has(before)) return '<div class="diff-simple" style="color:#64748b">[循环引用]</div>';
        seen.before.add(before);
    }
    if (after !== null && typeof after === 'object') {
        if (seen.after.has(after)) return '<div class="diff-simple" style="color:#64748b">[循环引用]</div>';
        seen.after.add(after);
    }
    if (before === null || before === undefined || after === null || after === undefined) {
        return fallbackTextDiff(before, after);
    }
    if (typeof before !== 'object' || typeof after !== 'object') {
        return '<div class="diff-simple"><span class="diff-old">' + _esc(String(before)) + '</span><span class="diff-arrow">→</span><span class="diff-new">' + _esc(String(after)) + '</span></div>';
    }
    if (Array.isArray(before) !== Array.isArray(after)) {
        return fallbackTextDiff(before, after);
    }
    if (_jsonEqual(before, after)) {
        return '<pre style="color:#64748b;margin:0">' + _esc(JSON.stringify(before, null, 2)) + '</pre>';
    }
    if (Array.isArray(before)) {
        return renderArrayDiff(before, after, depth, seen);
    }
    const keys = Array.from(new Set([...Object.keys(before), ...Object.keys(after)])).sort();
    const indent = '  '.repeat(depth);
    const rows = [];
    for (const key of keys) {
        const hasB = key in before;
        const hasA = key in after;
        const bVal = before[key];
        const aVal = after[key];
        const label = indent + '"' + key + '": ';
        if (!hasB) {
            rows.push(renderNested(label, null, aVal, 'add', depth, seen));
        } else if (!hasA) {
            rows.push(renderNested(label, bVal, null, 'del', depth, seen));
        } else if (_jsonEqual(bVal, aVal)) {
            rows.push(renderNested(label, bVal, aVal, 'same', depth, seen));
        } else if (typeof bVal === 'object' && bVal !== null && typeof aVal === 'object' && aVal !== null) {
            rows.push('<div class="diff-line diff-same">' + _esc(label) + '{</div>');
            rows.push(renderStructuredDiff(bVal, aVal, depth + 1, seen));
            rows.push('<div class="diff-line diff-same">' + _esc(indent) + '}</div>');
        } else {
            rows.push('<div class="diff-line diff-mod">' + _esc(label) + '<span class="diff-old">' + _esc(JSON.stringify(bVal)) + '</span><span class="diff-arrow">→</span><span class="diff-new">' + _esc(JSON.stringify(aVal)) + '</span></div>');
        }
    }
    return '<div class="struct-diff">' + rows.join('') + '</div>';
}

function renderNested(label, bVal, aVal, mode, depth, seen) {
    const val = mode === 'del' ? bVal : aVal;
    if (val !== null && typeof val === 'object') {
        if (mode === 'same') {
            const s = JSON.stringify(val);
            return '<div class="diff-line diff-same">' + _esc(label) + '<span style="color:#64748b">' + _esc(s.length > 60 ? s.slice(0, 57) + '...' : s) + '</span></div>';
        }
        const isArr = Array.isArray(val);
        const cls = mode === 'add' ? 'diff-add' : 'diff-del';
        const other = isArr ? [] : {};
        const rows = [];
        rows.push('<div class="diff-line ' + cls + '">' + _esc(label) + (isArr ? '[' : '{') + '</div>');
        rows.push(renderStructuredDiff(mode === 'add' ? other : val, mode === 'add' ? val : other, depth + 1, seen));
        rows.push('<div class="diff-line ' + cls + '">' + _esc('  '.repeat(depth)) + (isArr ? ']' : '}') + '</div>');
        return rows.join('');
    }
    const s = JSON.stringify(val);
    const color = mode === 'same' ? '#64748b' : (mode === 'add' ? '#86efac' : '#fca5a5');
    const cls = mode === 'same' ? 'diff-same' : (mode === 'add' ? 'diff-add' : 'diff-del');
    return '<div class="diff-line ' + cls + '">' + _esc(label) + '<span style="color:' + color + '">' + _esc(s) + '</span></div>';
}

function renderArrayDiff(before, after, depth, seen) {
    if (before.length > 30 || after.length > 30) {
        return '<div class="diff-simple" style="color:#64748b">[数组 ' + before.length + ' → ' + after.length + ' 项，已折叠]</div>';
    }
    const hasUuid = before.concat(after).every(function(x) { return x && typeof x === 'object' && x.__uuid__; });
    if (hasUuid) return renderUuidArrayDiff(before, after, depth, seen);
    const maxLen = Math.max(before.length, after.length);
    const indent = '  '.repeat(depth);
    const rows = [];
    for (let i = 0; i < maxLen; i++) {
        const hasB = i < before.length;
        const hasA = i < after.length;
        const label = indent + '[' + i + ']: ';
        if (!hasB) {
            rows.push(renderNested(label, null, after[i], 'add', depth, seen));
        } else if (!hasA) {
            rows.push(renderNested(label, before[i], null, 'del', depth, seen));
        } else if (_jsonEqual(before[i], after[i])) {
            rows.push(renderNested(label, before[i], after[i], 'same', depth, seen));
        } else if (typeof before[i] === 'object' && before[i] !== null && typeof after[i] === 'object' && after[i] !== null) {
            rows.push('<div class="diff-line diff-same">' + _esc(label) + '{</div>');
            rows.push(renderStructuredDiff(before[i], after[i], depth + 1, seen));
            rows.push('<div class="diff-line diff-same">' + _esc(indent) + '}</div>');
        } else {
            rows.push('<div class="diff-line diff-mod">' + _esc(label) + '<span class="diff-old">' + _esc(JSON.stringify(before[i])) + '</span><span class="diff-arrow">→</span><span class="diff-new">' + _esc(JSON.stringify(after[i])) + '</span></div>');
        }
    }
    return '<div class="struct-diff">' + rows.join('') + '</div>';
}

function renderUuidArrayDiff(before, after, depth, seen) {
    const bMap = {}, aMap = {};
    before.forEach(function(x, i) { bMap[x.__uuid__] = {item: x, idx: i}; });
    after.forEach(function(x, i) { aMap[x.__uuid__] = {item: x, idx: i}; });
    const all = new Set([...Object.keys(bMap), ...Object.keys(aMap)]);
    const indent = '  '.repeat(depth);
    const rows = [];
    for (const uuid of all) {
        const bItem = bMap[uuid];
        const aItem = aMap[uuid];
        const label = indent + '"' + uuid.substring(0, 8) + '...": ';
        if (!bItem) {
            rows.push(renderNested(label, null, aItem.item, 'add', depth, seen));
        } else if (!aItem) {
            rows.push(renderNested(label, bItem.item, null, 'del', depth, seen));
        } else if (_jsonEqual(bItem.item, aItem.item)) {
            rows.push(renderNested(label, bItem.item, aItem.item, 'same', depth, seen));
        } else {
            rows.push('<div class="diff-line diff-same">' + _esc(label) + '{</div>');
            rows.push(renderStructuredDiff(bItem.item, aItem.item, depth + 1, seen));
            rows.push('<div class="diff-line diff-same">' + _esc(indent) + '}</div>');
        }
    }
    return '<div class="struct-diff">' + rows.join('') + '</div>';
}

function _jsonEqual(a, b) {
    return JSON.stringify(a) === JSON.stringify(b);
}

function fallbackTextDiff(before, after) {
    return '<div class="json-diff">' +
        '<div class="json-diff-col"><div class="json-diff-title">旧值</div><pre>' + _esc(JSON.stringify(before, null, 2)) + '</pre></div>' +
        '<div class="json-diff-col"><div class="json-diff-title">新值</div><pre>' + _esc(JSON.stringify(after, null, 2)) + '</pre></div>' +
        '</div>';
}

function _esc(s) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(String(s)));
    return div.innerHTML;
}

function openModal() {
    document.getElementById('confidenceModal').classList.add('active');
}
function closeModal(e) {
    if (!e || e.target.id === 'confidenceModal') {
        document.getElementById('confidenceModal').classList.remove('active');
    }
}
</script>
</body>
</html>
"""

