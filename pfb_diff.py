#!/usr/bin/env python3
import argparse
import os
import sys
import time

from diff_engine import diff_prefabs
from report_html import write_html_report
from report_html_tree import write_html_report as write_html_tree_report
from report_json import write_json_report


def main(p_args=None):
    t_parser = argparse.ArgumentParser(description="Cocos Creator 2.x prefab semantic diff")
    t_sub = t_parser.add_subparsers(dest="command")
    t_diff = t_sub.add_parser("diff", help="diff two prefab files")
    t_diff.add_argument("--before", required=True, help="old prefab file")
    t_diff.add_argument("--after", required=True, help="new prefab file")
    t_diff.add_argument("--out", help="html report path (tree view by default)")
    t_diff.add_argument("--out-classic", dest="out_classic", help="classic table-based html report path")
    t_diff.add_argument("--json", dest="json_out", help="json report path")
    t_diff.add_argument("--fail-on-risk", choices=["medium", "high"], help="return non-zero when risk exists")

    t_ns = t_parser.parse_args(p_args)
    if t_ns.command != "diff":
        t_parser.print_help()
        return 2

    if not t_ns.json_out and not t_ns.out and not t_ns.out_classic:
        t_paths = _default_report_paths(t_ns.before, t_ns.after)
        t_ns.out = t_paths["html"]
        t_ns.json_out = t_paths["json"]

    t_result = diff_prefabs(t_ns.before, t_ns.after)
    if t_ns.json_out:
        write_json_report(t_result, t_ns.json_out)
        print("JSON report: %s" % t_ns.json_out)
    if t_ns.out:
        write_html_tree_report(t_result, t_ns.out)
        print("HTML report: %s" % t_ns.out)
    if t_ns.out_classic:
        write_html_report(t_result, t_ns.out_classic)
        print("Classic HTML report: %s" % t_ns.out_classic)

    if t_ns.fail_on_risk:
        t_risks = t_result.summary.get("by_risk", {})
        if t_ns.fail_on_risk == "high" and t_risks.get("high"):
            return 1
        if t_ns.fail_on_risk == "medium" and (t_risks.get("high") or t_risks.get("medium")):
            return 1
    return 0


def _default_report_paths(p_before: str, p_after: str, p_create_dir: bool = True):
    if hasattr(sys, '_MEIPASS'):
        t_tool_dir = os.path.dirname(sys.executable)
    else:
        t_tool_dir = os.path.dirname(os.path.abspath(__file__))
    t_report_dir = os.path.join(t_tool_dir, "reports", "compare")
    if p_create_dir and not os.path.isdir(t_report_dir):
        os.makedirs(t_report_dir)
    t_before_name = _prefab_base_name(p_before)
    t_after_name = _prefab_base_name(p_after)
    t_stamp = time.strftime("%Y%m%d_%H%M%S")
    if t_before_name == t_after_name:
        t_base = "%s_diff_%s" % (t_before_name, t_stamp)
    else:
        t_base = "%s__to__%s_%s" % (t_before_name, t_after_name, t_stamp)
    return {
        "html": os.path.join(t_report_dir, t_base + ".html"),
        "json": os.path.join(t_report_dir, t_base + ".json"),
    }


def _prefab_base_name(p_path: str) -> str:
    t_name = os.path.basename(p_path).replace("\\", "/")
    t_name = os.path.basename(t_name)
    if t_name.endswith(".prefab"):
        t_name = t_name[:-7]
    return _safe_file_name(t_name or "prefab")


def _safe_file_name(p_name: str) -> str:
    t_chars = []
    for t_char in p_name:
        if t_char.isalnum() or t_char in ("-", "_", "."):
            t_chars.append(t_char)
        else:
            t_chars.append("_")
    return "".join(t_chars)


if __name__ == "__main__":
    sys.exit(main())
