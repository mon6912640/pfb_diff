import html
import json
import os


def write_html_report(p_result, p_file_path):
    with open(p_file_path, "w", encoding="utf-8") as p_file:
        p_file.write(render_html(p_result))


def render_html(p_result):
    t_real_changes = [t_change for t_change in p_result.changes if t_change.category != "warning"]
    t_warnings = p_result.warnings
    t_low_confidence = [t_match for t_match in p_result.matches if t_match.get("status") in ("uncertain", "ambiguous")]
    return """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>PfbDiff Report</title>
<style>
body{font-family:Arial,"Microsoft YaHei",sans-serif;margin:0;color:#222;background:#f3f5f7}
.wrap{max-width:1180px;margin:0 auto;padding:24px}
h1{font-size:24px;margin:0 0 14px}
h2{font-size:18px;margin:24px 0 10px}
h3{font-size:15px;margin:16px 0 8px}
.panel{background:#fff;border:1px solid #dfe3e8;border-radius:6px;padding:14px 16px;margin:12px 0}
.conclusion{font-size:15px;line-height:1.7}
.good{color:#1b5e20;font-weight:bold}.warn{color:#9a6500;font-weight:bold}.bad{color:#b00020;font-weight:bold}
.muted{color:#667085}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.stat{background:#fff;border:1px solid #dfe3e8;border-radius:6px;padding:12px}
.stat b{display:block;font-size:22px;margin-bottom:4px}
table{border-collapse:collapse;width:100%%;background:#fff;margin:10px 0 18px}
th,td{border:1px solid #dfe3e8;padding:8px 10px;font-size:13px;vertical-align:top}
th{background:#f0f2f5;text-align:left}
code,pre{white-space:pre-wrap;word-break:break-all}
details{margin-top:6px}
summary{cursor:pointer;color:#3451b2}
.tag{display:inline-block;border-radius:4px;padding:2px 6px;font-size:12px;font-weight:bold}
.risk-high{background:#fde7e9;color:#b00020}.risk-medium{background:#fff4d6;color:#8a5a00}.risk-low{background:#e8f5e9;color:#1b5e20}
@media(max-width:760px){.wrap{padding:14px}.grid{grid-template-columns:1fr 1fr}th,td{font-size:12px;padding:6px}}
</style>
</head>
<body>
<div class="wrap">
<h1>PfbDiff 预制体对比报告</h1>
%s
%s
%s
%s
%s
</div>
</body>
</html>""" % (
        _file_panel(p_result),
        _conclusion_panel(p_result, t_real_changes, t_warnings, t_low_confidence),
        _real_changes_panel(t_real_changes),
        _low_confidence_panel(t_low_confidence),
        _warnings_panel(t_warnings),
    )


def _file_panel(p_result):
    return """<div class="panel">
<h2>对比文件</h2>
<table>
<tr><th>旧 prefab</th><td>%s</td></tr>
<tr><th>新 prefab</th><td>%s</td></tr>
</table>
</div>""" % (_e(_display_path(p_result.before_file)), _e(_display_path(p_result.after_file)))


def _conclusion_panel(p_result, p_real_changes, p_warnings, p_low_confidence):
    t_summary = p_result.summary or {}
    t_high_real = [t_change for t_change in p_real_changes if t_change.risk == "high"]
    t_node_changes = [t_change for t_change in p_real_changes if t_change.category == "node"]
    t_resource_changes = [t_change for t_change in p_real_changes if t_change.category == "resource"]
    t_event_changes = [t_change for t_change in p_real_changes if t_change.category == "event"]
    t_text = _conclusion_text(p_real_changes, p_warnings, p_low_confidence)
    return """<div class="panel conclusion">
<h2>结论</h2>
<p>%s</p>
<div class="grid">
<div class="stat"><b>%s</b><span>实际差异</span></div>
<div class="stat"><b>%s</b><span>高风险实际差异</span></div>
<div class="stat"><b>%s</b><span>节点变化</span></div>
<div class="stat"><b>%s</b><span>解析警告</span></div>
</div>
<p class="muted">匹配节点数：%s；资源变化：%s；事件变化：%s。</p>
</div>""" % (
        t_text,
        len(p_real_changes),
        len(t_high_real),
        len(t_node_changes),
        len(p_warnings),
        _e(t_summary.get("match_count", 0)),
        len(t_resource_changes),
        len(t_event_changes),
    )


def _conclusion_text(p_real_changes, p_warnings, p_low_confidence):
    if not p_real_changes and not p_warnings:
        return '<span class="good">两个 prefab 没有发现差异。</span>'
    if not p_real_changes and p_warnings:
        return '<span class="warn">没有发现实际内容差异，但存在解析警告。通常表示 prefab 内部有无效引用，需要单独检查。</span>'
    if len(p_real_changes) == 1 and not p_low_confidence:
        return '<span class="good">只发现 1 处实际内容差异，且节点匹配明确。</span>'
    if p_low_confidence:
        return '<span class="bad">存在低置信度匹配，建议人工确认这些节点是否真的是同一个节点。</span>'
    return '<span class="warn">发现 %s 处实际内容差异，请查看下面的差异列表。</span>' % len(p_real_changes)


def _real_changes_panel(p_changes):
    if not p_changes:
        return '<div class="panel"><h2>真正的 prefab 差异</h2><p class="good">无实际内容差异。</p></div>'
    t_rows = []
    for t_change in p_changes:
        t_rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            _risk_tag(t_change.risk),
            _e(_plain_change_type(t_change)),
            _e(_change_target(t_change)),
            _e(_plain_change_summary(t_change)),
            _detail_block(t_change),
        ))
    return """<div class="panel">
<h2>真正的 prefab 差异</h2>
<table>
<tr><th>风险</th><th>变化类型</th><th>位置</th><th>说明</th><th>详情</th></tr>
%s
</table>
</div>""" % "".join(t_rows)


def _low_confidence_panel(p_matches):
    if not p_matches:
        return '<div class="panel"><h2>需要人工确认的匹配</h2><p class="good">无。所有已匹配节点都比较明确。</p></div>'
    t_rows = []
    for t_match in p_matches:
        t_rows.append("<tr><td>%s</td><td>%s</td><td>%s => %s</td><td>%s</td></tr>" % (
            _e(t_match.get("status")),
            _e(t_match.get("confidence")),
            _e(t_match.get("before_path")),
            _e(t_match.get("after_path")),
            _e(", ".join(t_match.get("reasons") or [])),
        ))
    return """<div class="panel">
<h2>需要人工确认的匹配</h2>
<p class="muted">这里列出的节点，工具认为可能是同一个节点，但证据不够强。</p>
<table><tr><th>状态</th><th>置信度</th><th>节点</th><th>匹配依据</th></tr>%s</table>
</div>""" % "".join(t_rows)


def _warnings_panel(p_warnings):
    if not p_warnings:
        return '<div class="panel"><h2>解析警告</h2><p class="good">无。</p></div>'
    t_rows = []
    for t_warning in p_warnings:
        t_rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            _e(_side_name(t_warning.get("side"))),
            _e(_warning_type(t_warning)),
            _e(_warning_summary(t_warning)),
            _json_details(t_warning),
        ))
    return """<div class="panel">
<h2>解析警告</h2>
<p class="muted">解析警告不一定表示两个 prefab 有差异。它表示 prefab 内部引用不完整，可能是 Cocos 序列化特殊结构，也可能是坏引用。</p>
<table><tr><th>文件</th><th>类型</th><th>说明</th><th>原始信息</th></tr>%s</table>
</div>""" % "".join(t_rows)


def _plain_change_type(p_change):
    t_map = {
        "added": "新增节点",
        "deleted": "删除节点",
        "moved": "节点移动",
        "renamed": "节点重命名",
        "moved_and_renamed": "节点移动并重命名",
        "child_order_changed": "子节点顺序变化",
        "changed": "字段变化",
        "order_changed": "组件顺序变化",
        "uncertain": "低置信度匹配",
        "ambiguous": "多候选匹配",
    }
    return t_map.get(p_change.type, p_change.type)


def _plain_change_summary(p_change):
    if p_change.category == "resource":
        return "资源引用变化：%s" % (p_change.field or "")
    if p_change.category == "event":
        return "按钮事件变化：%s" % (p_change.field or "")
    if p_change.category == "field":
        if p_change.field and "_clips" in p_change.field:
            return _clips_summary(p_change.before, p_change.after)
        return "字段 %s 的值发生变化" % (p_change.field or "")
    if p_change.category == "component":
        return "组件 %s 发生变化" % (p_change.field or "")
    if p_change.type == "moved_and_renamed":
        return "%s 移动并重命名为 %s" % (p_change.before_path, p_change.after_path)
    if p_change.type == "moved":
        return "%s 移动到 %s" % (p_change.before_path, p_change.after_path)
    if p_change.type == "renamed":
        return "%s 重命名为 %s" % (p_change.details.get("before_name"), p_change.details.get("after_name"))
    if p_change.type == "added":
        return "新增节点 %s" % p_change.after_path
    if p_change.type == "deleted":
        return "删除节点 %s" % p_change.before_path
    return p_change.type


def _clips_summary(p_before, p_after):
    t_before = _uuid_list(p_before)
    t_after = _uuid_list(p_after)
    t_added = [t_uuid for t_uuid in t_after if t_uuid not in t_before]
    t_deleted = [t_uuid for t_uuid in t_before if t_uuid not in t_after]
    t_parts = []
    if t_added:
        t_parts.append("动画 clip 新增 %s 个" % len(t_added))
    if t_deleted:
        t_parts.append("动画 clip 删除 %s 个" % len(t_deleted))
    if not t_parts:
        t_parts.append("动画 clip 顺序或内容发生变化")
    return "；".join(t_parts)


def _uuid_list(p_value):
    t_values = []
    if isinstance(p_value, list):
        for t_item in p_value:
            if isinstance(t_item, dict) and t_item.get("__uuid__"):
                t_values.append(t_item.get("__uuid__"))
    return t_values


def _change_target(p_change):
    if p_change.before_path and p_change.after_path and p_change.before_path != p_change.after_path:
        return "%s => %s" % (p_change.before_path, p_change.after_path)
    return p_change.after_path or p_change.before_path or ""


def _detail_block(p_change):
    return """<details>
<summary>查看原始值</summary>
<h3>旧值</h3><pre>%s</pre>
<h3>新值</h3><pre>%s</pre>
<h3>内部信息</h3><pre>%s</pre>
</details>""" % (
        _e(json.dumps(p_change.before, ensure_ascii=False, sort_keys=True, indent=2)),
        _e(json.dumps(p_change.after, ensure_ascii=False, sort_keys=True, indent=2)),
        _e(json.dumps({
            "category": p_change.category,
            "type": p_change.type,
            "field": p_change.field,
            "confidence": p_change.confidence,
            "before_internal_path": p_change.before_internal_path,
            "after_internal_path": p_change.after_internal_path,
            "details": p_change.details,
        }, ensure_ascii=False, sort_keys=True, indent=2)),
    )


def _json_details(p_value):
    return "<details><summary>查看</summary><pre>%s</pre></details>" % _e(json.dumps(p_value, ensure_ascii=False, sort_keys=True, indent=2))


def _risk_tag(p_risk):
    t_name = {"high": "高", "medium": "中", "low": "低"}.get(p_risk, p_risk)
    return '<span class="tag risk-%s">%s</span>' % (_e(p_risk), _e(t_name))


def _side_name(p_side):
    if p_side == "before":
        return "旧 prefab"
    if p_side == "after":
        return "新 prefab"
    return p_side or ""


def _warning_type(p_warning):
    if p_warning.get("type") == "invalid_child_ref":
        return "无效子节点引用"
    return p_warning.get("type", "")


def _warning_summary(p_warning):
    if p_warning.get("type") == "invalid_child_ref":
        return "节点 id=%s 引用了不存在的子节点 id=%s" % (p_warning.get("id"), p_warning.get("ref_id"))
    return p_warning.get("message", "")


def _display_path(p_path):
    if not p_path:
        return ""
    return p_path.replace("\\", "/")


def _e(p_value):
    return html.escape("" if p_value is None else str(p_value), quote=True)
