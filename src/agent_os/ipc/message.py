from dataclasses import dataclass, field
import time
from typing import Any
import uuid

@dataclass
class Message:
    sender_pid: int
    receiver_pid: int
    payload: Any
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sequence_number: int = 0
    correlation_id: str | None = None
    message_type: str = 'DATA'
    timestamp: float = field(default_factory=time.time)
    delivery_status: str = 'PENDING'
