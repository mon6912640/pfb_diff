from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional


@dataclass
class Change:
    category: str
    type: str
    risk: str
    before_path: Optional[str] = None
    after_path: Optional[str] = None
    before_internal_path: Optional[str] = None
    after_internal_path: Optional[str] = None
    field: Optional[str] = None
    before: Any = None
    after: Any = None
    confidence: int = 100
    details: Dict[str, Any] = dc_field(default_factory=dict)


@dataclass
class DiffResult:
    before_file: str
    after_file: str
    before_path: str = ""
    after_path: str = ""
    summary: Dict[str, Any] = dc_field(default_factory=dict)
    matches: List[Dict[str, Any]] = dc_field(default_factory=list)
    changes: List[Change] = dc_field(default_factory=list)
    warnings: List[Dict[str, Any]] = dc_field(default_factory=list)
