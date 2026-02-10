from dataclasses import dataclass, field
import time
from typing import List, Optional

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
    parent_packet_id: Optional[int] = None
    
    def __init__(self, packet_id: int, matrix_event_id: Optional[str], 
                 sender: str, original_text: str = None, text: str = None,
                 reception_list: List[ReceptionStats] = None,
                 replies: List[str] = None,
                 last_update: float = None,
                 render_only_stats: bool = False,
                 related_event_id: Optional[str] = None,
                 parent_packet_id: Optional[int] = None):
        # Support both 'text' and 'original_text' for backwards compatibility
        if original_text is None and text is not None:
            original_text = text
        elif original_text is None and text is None:
            original_text = ""
            
        self.packet_id = packet_id
        self.matrix_event_id = matrix_event_id
        self.original_text = original_text
        self.sender = sender
        self.reception_list = reception_list if reception_list is not None else []
        self.replies = replies if replies is not None else []
        self.last_update = last_update if last_update is not None else time.time()
        self.render_only_stats = render_only_stats
        self.related_event_id = related_event_id
        self.parent_packet_id = parent_packet_id
