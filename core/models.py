from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from enum import Enum
import json
from typing import Optional, Dict, Any, List


class CheckStatus(Enum):
    """Status of username check on a site."""
    FOUND = "found"
    NOT_FOUND = "not_found"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    CHECKING = "checking"


class EventType(Enum):
    """Types of streaming events dispatched during search."""
    SEARCH_STARTED = "search_started"
    SITE_CHECKING = "site_checking"
    SITE_RESULT = "site_result"
    SEARCH_PROGRESS = "search_progress"
    SEARCH_COMPLETED = "search_completed"
    ERROR = "error"
    DUCKDUCKGO_STARTED = "duckduckgo_started"
    DUCKDUCKGO_RESULT = "duckduckgo_result"
    PROFILE_EXTRACTED = "profile_extracted"


def serialize_enum_dict(data: Any) -> Any:
    """Recursively serialize enum values in structures to string values."""
    if isinstance(data, dict):
        return {key: serialize_enum_dict(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [serialize_enum_dict(item) for item in data]
    elif isinstance(data, Enum):
        return data.value
    return data


@dataclass
class StreamEvent:
    """Streamed event for SSE, WebSockets, or CLI observers."""
    event_type: EventType
    data: Dict[str, Any]
    timestamp: Optional[str] = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        d["data"] = serialize_enum_dict(d["data"])
        return d

    def to_sse(self) -> str:
        return f"data: {json.dumps(self.to_dict())}\n\n"

    def to_json(self) -> Dict[str, Any]:
        return self.to_dict()


@dataclass
class SiteResult:
    """Result from checking a single website."""
    site_name: str
    category: str
    url: str
    status: CheckStatus
    status_code: Optional[int] = None
    profile_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    response_time: Optional[float] = None
    checked_at: Optional[str] = None

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass
class SiteCheckOutcome:
    """Internal check outcome including raw text for profile extraction."""
    result: SiteResult
    response_text: Optional[str] = None
