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


def fixture(p_name):
    return os.path.join(FIXTURES, p_name)


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
