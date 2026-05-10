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
