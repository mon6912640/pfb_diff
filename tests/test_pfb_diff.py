import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from diff_engine import diff_prefabs
from prefab_parser import parse_prefab
from pfb_diff import _default_report_paths, _prefab_base_name
from report_html import write_html_report
from report_html_tree import write_html_report as write_html_tree_report
from report_json import write_json_report

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
TEST_PFB = os.path.join(ROOT, "testPfb")


def fixture(p_name):
    return os.path.join(FIXTURES, p_name)


def test_pfb(p_name):
    return os.path.join(TEST_PFB, p_name)


def score_part(p_match, p_reason):
    for t_part in p_match.get("score", {}).get("parts", []):
        if t_part.get("reason") == p_reason:
            return t_part
    return None


def id_shifted_copy(p_data):
    """模拟"文件前部插入一个对象"：下标 ≥1 的对象整体后移，所有 __id__ 引用 +1。

    语义完全等价，仅 __id__ 布局不同——diff 必须报 0 个变化。
    """
    def shift(p_value):
        if isinstance(p_value, dict):
            if "__id__" in p_value and isinstance(p_value["__id__"], int):
                t_id = p_value["__id__"]
                return {"__id__": t_id + 1 if t_id >= 1 else t_id}
            return {t_key: shift(t_item) for t_key, t_item in p_value.items()}
        if isinstance(p_value, list):
            return [shift(t_item) for t_item in p_value]
        return p_value

    return [shift(p_data[0]), {"__type__": "cc.JsonAsset", "_name": "__pad__"}] + [shift(t_obj) for t_obj in p_data[1:]]


def toggle_prefab(p_handler):
    return [
        {"__type__": "cc.Prefab", "data": {"__id__": 1}},
        {"__type__": "cc.Node", "_name": "Root", "_children": [], "_components": [{"__id__": 2}]},
        {"__type__": "cc.Toggle", "node": {"__id__": 1},
         "checkEvents": [{"__type__": "cc.ClickEvent", "target": {"__id__": 1}, "component": "MyView", "handler": p_handler, "customEventData": ""}]},
    ]


def retarget_prefab(p_target_id):
    return [
        {"__type__": "cc.Prefab", "data": {"__id__": 1}},
        {"__type__": "cc.Node", "_name": "Root", "_children": [{"__id__": 2}, {"__id__": 3}], "_components": [{"__id__": 4}]},
        {"__type__": "cc.Node", "_name": "TargetA", "_parent": {"__id__": 1}, "_children": [], "_components": []},
        {"__type__": "cc.Node", "_name": "TargetB", "_parent": {"__id__": 1}, "_children": [], "_components": []},
        {"__type__": "cc.Button", "node": {"__id__": 1},
         "clickEvents": [{"__type__": "cc.ClickEvent", "target": {"__id__": p_target_id}, "component": "MyView", "handler": "onClick", "customEventData": ""}]},
    ]


def write_temp_prefab(p_dir, p_name, p_data):
    t_path = os.path.join(p_dir, p_name)
    with open(t_path, "w", encoding="utf-8") as t_file:
        json.dump(p_data, t_file, ensure_ascii=False)
    return t_path


def empty_container_prefab(p_container_name, p_child_names):
    """一个无组件的纯容器，挂若干无特征的空子节点。用于跨名空容器误配测试。"""
    t_data = [
        {"__type__": "cc.Prefab", "data": {"__id__": 1}},
        {"__type__": "cc.Node", "_name": "Root", "_children": [{"__id__": 2}], "_components": []},
        {"__type__": "cc.Node", "_name": p_container_name, "_parent": {"__id__": 1},
         "_children": [{"__id__": 3 + t_i} for t_i in range(len(p_child_names))], "_components": []},
    ]
    for t_i, t_name in enumerate(p_child_names):
        t_data.append({"__type__": "cc.Node", "_name": t_name, "_parent": {"__id__": 2}, "_children": [], "_components": []})
    return t_data


def refactored_node_prefab(p_component_type):
    """同名同路径节点，仅组件类型不同（模拟 cc.Label → cc.RichText 重构）。"""
    return [
        {"__type__": "cc.Prefab", "data": {"__id__": 1}},
        {"__type__": "cc.Node", "_name": "Root", "_children": [{"__id__": 2}], "_components": []},
        {"__type__": "cc.Node", "_name": "Tip", "_parent": {"__id__": 1}, "_children": [], "_components": [{"__id__": 3}]},
        {"__type__": p_component_type, "node": {"__id__": 2}},
    ]


def duplicate_identity_prefab(p_first_parent, p_second_parent):
    return [
        {"__type__": "cc.Prefab", "data": {"__id__": 1}},
        {"__type__": "cc.Node", "_name": "Root", "_children": [{"__id__": 2}, {"__id__": 4}], "_components": []},
        {"__type__": "cc.Node", "_name": p_first_parent, "_parent": {"__id__": 1}, "_children": [{"__id__": 3}], "_components": []},
        {"__type__": "cc.Node", "_name": "Prize", "_parent": {"__id__": 2}, "_children": [], "_components": [{"__id__": 6}]},
        {"__type__": "cc.Node", "_name": p_second_parent, "_parent": {"__id__": 1}, "_children": [{"__id__": 5}], "_components": []},
        {"__type__": "cc.Node", "_name": "Prize", "_parent": {"__id__": 4}, "_children": [], "_components": [{"__id__": 7}]},
        {"__type__": "cc.Sprite", "node": {"__id__": 3}, "_spriteFrame": {"__uuid__": "same-sprite"}},
        {"__type__": "cc.Sprite", "node": {"__id__": 5}, "_spriteFrame": {"__uuid__": "same-sprite"}},
    ]


class PfbDiffTests(unittest.TestCase):
    def test_identical_prefab_has_no_changes(self):
        t_result = diff_prefabs(fixture("base.prefab"), fixture("base.prefab"))
        self.assertEqual([], [t_change for t_change in t_result.changes if t_change.category != "warning"])

    def test_label_text_change_is_field_change(self):
        t_result = diff_prefabs(fixture("base.prefab"), fixture("label_changed.prefab"))
        self.assertTrue(any(t_change.category == "field" and "_N$string" in t_change.field for t_change in t_result.changes))

    def test_sprite_uuid_change_is_resource_change(self):
        t_result = diff_prefabs(fixture("base.prefab"), fixture("sprite_changed.prefab"))
        self.assertTrue(any(t_change.category == "resource" and t_change.before == "sprite-a" and t_change.after == "sprite-b" for t_change in t_result.changes))

    def test_button_event_change_is_event_change(self):
        t_result = diff_prefabs(fixture("base.prefab"), fixture("button_event_changed.prefab"))
        self.assertTrue(any(t_change.category == "event" and t_change.risk == "high" for t_change in t_result.changes))

    def test_move_is_not_delete_plus_add(self):
        t_result = diff_prefabs(fixture("base.prefab"), fixture("moved.prefab"))
        t_types = [(t_change.category, t_change.type) for t_change in t_result.changes]
        self.assertIn(("node", "moved"), t_types)
        self.assertNotIn(("node", "deleted"), t_types)
        self.assertNotIn(("node", "added"), t_types)

    def test_moved_match_includes_score_parts(self):
        t_result = diff_prefabs(fixture("base.prefab"), fixture("moved.prefab"))
        t_match = next(t_match for t_match in t_result.matches if t_match["before_path"] == "Root/BtnReward")
        self.assertEqual(100, t_match["score"]["total"])
        self.assertEqual("identity", score_part(t_match, "same_unique_identity_hash")["kind"])
        t_change = next(t_change for t_change in t_result.changes if t_change.category == "node" and t_change.type == "moved")
        self.assertEqual(t_match["score"], t_change.details["score"])

    def test_same_identity_prefers_same_path_when_ambiguous(self):
        t_result = diff_prefabs(fixture("ambiguous_identity_before.prefab"), fixture("ambiguous_identity_after.prefab"))
        t_moved_paths = [
            (t_change.before_path, t_change.after_path)
            for t_change in t_result.changes
            if t_change.category == "node" and t_change.type == "moved"
        ]
        self.assertNotIn(("TowBat/tc/SpriteBg3/Layout", "TowBat/UIAct/Layout"), t_moved_paths)
        self.assertTrue(any(
            t_change.category == "node"
            and t_change.type == "added"
            and t_change.after_path == "TowBat/UIAct/Layout"
            for t_change in t_result.changes
        ))

    def test_repeated_subtree_does_not_steal_same_path_match(self):
        t_result = diff_prefabs(test_pfb("gui_hcll.prefab"), test_pfb("hb_hcll.prefab"))
        t_moved_paths = [
            (t_change.before_path, t_change.after_path)
            for t_change in t_result.changes
            if t_change.category == "node" and t_change.type == "moved"
        ]
        self.assertNotIn(("Hcll/ndAYMLLv/ndLight", "Hcll/ndLv/ndLight"), t_moved_paths)
        self.assertTrue(any(
            t_match["before_path"] == "Hcll/ndLv/ndLight"
            and t_match["after_path"] == "Hcll/ndLv/ndLight"
            for t_match in t_result.matches
        ))

    def test_weak_layout_container_is_not_cross_path_confirmed(self):
        t_result = diff_prefabs(test_pfb("gui_hcll.prefab"), test_pfb("hb_hcll.prefab"))
        t_moved_paths = [
            (t_change.before_path, t_change.after_path)
            for t_change in t_result.changes
            if t_change.category == "node" and t_change.type == "moved"
        ]
        self.assertNotIn(("Hcll/bg/content", "Hcll/ScrollView/view/content"), t_moved_paths)

    def test_same_name_siblings_do_not_anchor_by_display_path(self):
        t_result = diff_prefabs(test_pfb("gui_ddp.prefab"), test_pfb("hb_ddp.prefab"))
        self.assertTrue(any(
            t_match["before_internal_path"] == "DDP[0]/btnTS[7]"
            and t_match["after_internal_path"] == "DDP[0]/btnTS[7]"
            for t_match in t_result.matches
        ))
        self.assertTrue(any(
            t_change.category == "node"
            and t_change.type == "moved"
            and t_change.before_internal_path == "DDP[0]/btnTS[14]"
            and t_change.after_internal_path == "DDP[0]/NdBtn[11]/btnTS[0]"
            for t_change in t_result.changes
        ))
        self.assertFalse(any(
            t_change.category == "node"
            and t_change.type == "deleted"
            and t_change.before_internal_path == "DDP[0]/btnTS[7]"
            for t_change in t_result.changes
        ))

    def test_score_breakdown_records_ddp_anchor_and_identity_rules(self):
        t_result = diff_prefabs(test_pfb("gui_ddp.prefab"), test_pfb("hb_ddp.prefab"))
        t_anchor = next(t_match for t_match in t_result.matches if t_match["before_internal_path"] == "DDP[0]/btnTS[7]")
        t_floor = score_part(t_anchor, "same_internal_path_anchor_floor")
        self.assertEqual("floor", t_floor["kind"])
        self.assertEqual(74, t_floor["value"])

        t_identity = next(t_match for t_match in t_result.matches if t_match["before_internal_path"] == "DDP[0]/btnTS[14]")
        self.assertEqual("DDP[0]/NdBtn[11]/btnTS[0]", t_identity["after_internal_path"])
        self.assertEqual("identity", score_part(t_identity, "same_unique_identity_hash")["kind"])

    def test_overlap_score_parts_include_set_math_details(self):
        t_result = diff_prefabs(test_pfb("gui_ddp.prefab"), test_pfb("hb_ddp.prefab"))
        t_match = next(t_match for t_match in t_result.matches if score_part(t_match, "child_name_overlap"))
        t_part = score_part(t_match, "child_name_overlap")
        self.assertEqual("overlap", t_part["kind"])
        self.assertIn("weight", t_part["details"])
        self.assertIn("intersection", t_part["details"])
        self.assertIn("union", t_part["details"])

    def test_duplicate_identity_score_records_cap(self):
        with tempfile.TemporaryDirectory() as t_dir:
            t_before = os.path.join(t_dir, "before.prefab")
            t_after = os.path.join(t_dir, "after.prefab")
            with open(t_before, "w", encoding="utf-8") as t_file:
                json.dump(duplicate_identity_prefab("Left", "Right"), t_file)
            with open(t_after, "w", encoding="utf-8") as t_file:
                json.dump(duplicate_identity_prefab("Top", "Bottom"), t_file)

            t_result = diff_prefabs(t_before, t_after)

        t_match = next(t_match for t_match in t_result.matches if score_part(t_match, "duplicate_identity_cap"))
        t_cap = score_part(t_match, "duplicate_identity_cap")
        self.assertEqual("cap", t_cap["kind"])
        self.assertEqual(91, t_cap["value"])

    def test_id_shift_produces_no_changes(self):
        """不变量：仅 __id__ 布局偏移、语义等价的两个文件，diff 必须为空。

        覆盖事件 target、props 引用剔除等所有 id 敏感路径；
        对 fixtures 和 testPfb 全部真实 prefab 各跑一遍。
        """
        t_files = sorted(
            t_path
            for t_dir in (FIXTURES, TEST_PFB)
            for t_path in (os.path.join(t_dir, t_name) for t_name in os.listdir(t_dir))
            if t_path.endswith(".prefab")
        )
        self.assertTrue(t_files)
        for t_path in t_files:
            with open(t_path, "r", encoding="utf-8") as t_file:
                t_data = json.load(t_file)
            with tempfile.TemporaryDirectory() as t_dir:
                t_shifted = write_temp_prefab(t_dir, "shifted.prefab", id_shifted_copy(t_data))
                t_result = diff_prefabs(t_path, t_shifted)
            t_changes = [t_change for t_change in t_result.changes if t_change.category != "warning"]
            self.assertEqual([], t_changes, "id shift caused false positives in %s: %s" % (
                os.path.basename(t_path),
                [(t_change.category, t_change.type, t_change.field) for t_change in t_changes[:5]],
            ))

    def test_toggle_check_event_change_is_detected(self):
        with tempfile.TemporaryDirectory() as t_dir:
            t_before = write_temp_prefab(t_dir, "before.prefab", toggle_prefab("onToggleA"))
            t_after = write_temp_prefab(t_dir, "after.prefab", toggle_prefab("onToggleB"))
            t_result = diff_prefabs(t_before, t_after)
        t_events = [t_change for t_change in t_result.changes if t_change.category == "event"]
        self.assertEqual(1, len(t_events))
        self.assertEqual("high", t_events[0].risk)

    def test_event_retarget_is_still_detected(self):
        """target 解析成路径后，真实的换绑（同 handler 绑到另一个节点）仍要检出。"""
        with tempfile.TemporaryDirectory() as t_dir:
            t_before = write_temp_prefab(t_dir, "before.prefab", retarget_prefab(2))
            t_after = write_temp_prefab(t_dir, "after.prefab", retarget_prefab(3))
            t_result = diff_prefabs(t_before, t_after)
        t_events = [t_change for t_change in t_result.changes if t_change.category == "event"]
        self.assertEqual(1, len(t_events))
        self.assertEqual("high", t_events[0].risk)
        self.assertEqual("Root/TargetA", t_events[0].before[0]["target"])
        self.assertEqual("Root/TargetB", t_events[0].after[0]["target"])

    def test_crossname_empty_container_is_not_matched(self):
        """问题4：跨名 + 特征域全空 + 子节点不重叠的容器不应被误判为重命名，而是删除+新增。"""
        with tempfile.TemporaryDirectory() as t_dir:
            t_before = write_temp_prefab(t_dir, "before.prefab", empty_container_prefab("propBox", ["prop1", "prop2", "prop3"]))
            t_after = write_temp_prefab(t_dir, "after.prefab", empty_container_prefab("charBox", ["hero1", "hero2", "hero3"]))
            t_result = diff_prefabs(t_before, t_after)
        t_node_types = [(t_change.type, t_change.before_path or t_change.after_path)
                        for t_change in t_result.changes if t_change.category == "node"]
        self.assertIn(("deleted", "Root/propBox"), t_node_types)
        self.assertIn(("added", "Root/charBox"), t_node_types)
        self.assertFalse(any(t_type in ("renamed", "moved", "moved_and_renamed") and "Box" in t_path
                             for t_type, t_path in t_node_types))

    def test_samename_refactored_node_still_matches(self):
        """问题4 同名放行：同名同路径节点仅组件类型变化时仍应匹配（不拆成删除+新增）。"""
        with tempfile.TemporaryDirectory() as t_dir:
            t_before = write_temp_prefab(t_dir, "before.prefab", refactored_node_prefab("cc.Label"))
            t_after = write_temp_prefab(t_dir, "after.prefab", refactored_node_prefab("cc.RichText"))
            t_result = diff_prefabs(t_before, t_after)
        self.assertTrue(any(
            t_match["before_path"] == "Root/Tip" and t_match["after_path"] == "Root/Tip"
            and t_match["status"] != "unmatched"
            for t_match in t_result.matches
        ))
        self.assertFalse(any(
            t_change.category == "node" and t_change.type in ("deleted", "added")
            and (t_change.before_path == "Root/Tip" or t_change.after_path == "Root/Tip")
            for t_change in t_result.changes
        ))

    def test_null_label_does_not_crash(self):
        """A：同节点混有 null 与非空 Label 文本时，指纹构建不应崩溃。"""
        t_data = [
            {"__type__": "cc.Prefab", "data": {"__id__": 1}},
            {"__type__": "cc.Node", "_name": "Root", "_children": [{"__id__": 2}], "_components": []},
            {"__type__": "cc.Node", "_name": "T", "_parent": {"__id__": 1}, "_children": [],
             "_components": [{"__id__": 3}, {"__id__": 4}]},
            {"__type__": "cc.Label", "node": {"__id__": 2}, "_N$string": None},
            {"__type__": "cc.Label", "node": {"__id__": 2}, "_N$string": "hello"},
        ]
        with tempfile.TemporaryDirectory() as t_dir:
            t_path = write_temp_prefab(t_dir, "x.prefab", t_data)
            t_result = diff_prefabs(t_path, t_path)
        self.assertEqual([], [t_change for t_change in t_result.changes if t_change.category != "warning"])

    def test_multiple_same_type_resources_are_not_overwritten(self):
        """D：同节点两个 cc.Sprite，各自 uuid 变化都要报出，不能互相覆盖。"""
        def sprites(p_uuid_a, p_uuid_b):
            return [
                {"__type__": "cc.Prefab", "data": {"__id__": 1}},
                {"__type__": "cc.Node", "_name": "Root", "_children": [{"__id__": 2}], "_components": []},
                {"__type__": "cc.Node", "_name": "Dual", "_parent": {"__id__": 1}, "_children": [],
                 "_components": [{"__id__": 3}, {"__id__": 4}]},
                {"__type__": "cc.Sprite", "node": {"__id__": 2}, "_spriteFrame": {"__uuid__": p_uuid_a}},
                {"__type__": "cc.Sprite", "node": {"__id__": 2}, "_spriteFrame": {"__uuid__": p_uuid_b}},
            ]
        with tempfile.TemporaryDirectory() as t_dir:
            t_before = write_temp_prefab(t_dir, "before.prefab", sprites("u1", "u2"))
            t_after = write_temp_prefab(t_dir, "after.prefab", sprites("v1", "v2"))
            t_result = diff_prefabs(t_before, t_after)
        t_resource_changes = {(t_change.before, t_change.after)
                              for t_change in t_result.changes if t_change.category == "resource"}
        self.assertIn(("u1", "v1"), t_resource_changes)
        self.assertIn(("u2", "v2"), t_resource_changes)

    def test_orphan_node_emits_warning(self):
        """C：有 _parent 但未被父 _children 列出的节点应触发 unreachable_node 警告。"""
        t_data = [
            {"__type__": "cc.Prefab", "data": {"__id__": 1}},
            {"__type__": "cc.Node", "_name": "Root", "_parent": None, "_children": [], "_components": []},
            {"__type__": "cc.Node", "_name": "Ghost", "_parent": {"__id__": 1}, "_children": [], "_components": []},
        ]
        with tempfile.TemporaryDirectory() as t_dir:
            t_path = write_temp_prefab(t_dir, "orphan.prefab", t_data)
            t_doc = parse_prefab(t_path)
        self.assertTrue(any(t_warning["type"] == "unreachable_node" and t_warning["name"] == "Ghost"
                            for t_warning in t_doc.warnings))

    def test_rename_is_not_delete_plus_add(self):
        t_result = diff_prefabs(fixture("base.prefab"), fixture("renamed.prefab"))
        t_types = [(t_change.category, t_change.type) for t_change in t_result.changes]
        self.assertIn(("node", "renamed"), t_types)
        self.assertNotIn(("node", "deleted"), t_types)
        self.assertNotIn(("node", "added"), t_types)

    def test_move_and_rename_is_single_change(self):
        t_result = diff_prefabs(fixture("base.prefab"), fixture("moved_renamed.prefab"))
        t_types = [(t_change.category, t_change.type) for t_change in t_result.changes]
        self.assertIn(("node", "moved_and_renamed"), t_types)
        self.assertNotIn(("node", "deleted"), t_types)
        self.assertNotIn(("node", "added"), t_types)

    def test_same_name_siblings_internal_path_is_unique(self):
        t_doc = parse_prefab(fixture("same_name_siblings.prefab"))
        t_paths = [t_node.internal_path for t_node in t_doc.nodes]
        self.assertEqual(len(t_paths), len(set(t_paths)))
        self.assertTrue(any("Item[0]" in t_path for t_path in t_paths))
        self.assertTrue(any("Item[1]" in t_path for t_path in t_paths))

    def test_component_order_change_is_reported(self):
        t_result = diff_prefabs(fixture("base.prefab"), fixture("component_order_changed.prefab"))
        self.assertTrue(any(t_change.category == "component" and t_change.type == "order_changed" for t_change in t_result.changes))

    def test_invalid_ref_is_warning(self):
        t_result = diff_prefabs(fixture("base.prefab"), fixture("invalid_ref.prefab"))
        self.assertTrue(any(t_warning["type"] == "invalid_child_ref" for t_warning in t_result.warnings))
        self.assertTrue(any(t_change.category == "warning" and t_change.risk == "high" for t_change in t_result.changes))

    def test_reports_can_be_written(self):
        t_result = diff_prefabs(fixture("base.prefab"), fixture("moved.prefab"))
        with tempfile.TemporaryDirectory() as t_dir:
            t_json = os.path.join(t_dir, "report.json")
            t_html = os.path.join(t_dir, "report.html")
            write_json_report(t_result, t_json)
            write_html_report(t_result, t_html)
            self.assertTrue(os.path.getsize(t_json) > 0)
            self.assertTrue(os.path.getsize(t_html) > 0)

    def test_tree_report_can_be_written(self):
        t_result = diff_prefabs(fixture("base.prefab"), fixture("moved.prefab"))
        with tempfile.TemporaryDirectory() as t_dir:
            t_tree_html = os.path.join(t_dir, "tree_report.html")
            write_html_tree_report(t_result, t_tree_html)
            self.assertTrue(os.path.getsize(t_tree_html) > 0)
            with open(t_tree_html, "r", encoding="utf-8") as f:
                t_content = f.read()
            self.assertIn("tree-area", t_content)
            self.assertIn("chg-moved", t_content)
            self.assertIn("ALL_CHANGES", t_content)

    def test_default_report_paths_use_prefab_names(self):
        t_paths = _default_report_paths(fixture("base.prefab"), fixture("moved.prefab"), p_create_dir=False)
        self.assertTrue(t_paths["html"].endswith(".html"))
        self.assertTrue(t_paths["json"].endswith(".json"))
        self.assertIn("base__to__moved_", os.path.basename(t_paths["html"]))

    def test_prefab_base_name_accepts_windows_path(self):
        self.assertEqual("myflCnt", _prefab_base_name(r"C:\work\test\myflCnt.prefab"))


if __name__ == "__main__":
    unittest.main()
