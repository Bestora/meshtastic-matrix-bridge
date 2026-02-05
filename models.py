from dataclasses import dataclass, field
import time
from typing import List

@dataclass
class ReceptionStats:
    gateway_id: str
    rssi: int
    snr: float
    hop_count: int = 0
    timestamp: float = field(default_factory=time.time)

@dataclass
class MessageState:
    packet_id: int
    matrix_event_id: Optional[str] 
    original_text: str
    sender: str
    reception_list: List[ReceptionStats] = field(default_factory=list)
    replies: List[str] = field(default_factory=list)
    last_update: float = field(default_factory=time.time)
    render_only_stats: bool = False
    related_event_id: Optional[str] = None
