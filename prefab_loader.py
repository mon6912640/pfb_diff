import json
from typing import Any, Dict, List


def load_prefab_json(file_path: str) -> List[Dict[str, Any]]:
    with open(file_path, "r", encoding="utf-8") as p_file:
        t_data = json.load(p_file)
    if not isinstance(t_data, list):
        raise ValueError("prefab JSON root must be a list")
    return t_data
