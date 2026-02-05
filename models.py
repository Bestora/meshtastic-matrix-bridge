from dataclasses import dataclass, field
import time
from typing import List

@dataclass
class ReceptionStats:
    gateway_id: str
    rssi: int
    snr: float
    timestamp: float = field(default_factory=time.time)

@dataclass
class MessageState:
    packet_id: int
    matrix_event_id: str 
    original_text: str
    sender: str
    reception_list: List[ReceptionStats] = field(default_factory=list)
    last_update: float = field(default_factory=time.time)
