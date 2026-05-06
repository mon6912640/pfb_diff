import json
import sys
from dataclasses import asdict


def write_json_report(p_result, p_file_path):
    if p_file_path == "-":
        json.dump(to_json_data(p_result), sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return
    with open(p_file_path, "w", encoding="utf-8") as p_file:
        json.dump(to_json_data(p_result), p_file, ensure_ascii=False, indent=2, sort_keys=True)
        p_file.write("\n")


def to_json_data(p_result):
    return {
        "before_file": p_result.before_file,
        "after_file": p_result.after_file,
        "summary": p_result.summary,
        "matches": p_result.matches,
        "changes": [asdict(t_change) for t_change in p_result.changes],
        "warnings": p_result.warnings,
    }
