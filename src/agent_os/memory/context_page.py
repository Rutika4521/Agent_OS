import uuid
import time
from dataclasses import dataclass, field

@dataclass
class ContextPage:
    """
    ContextPage represents a single page of context memory.
    """
    process_id: int
    index: int
    content: str
    page_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content_reference: str = ""
    loaded: bool = True
    pinned: bool = False
    last_accessed: float = field(default_factory=time.time)
    version: int = 1
