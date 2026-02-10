from typing import List
from models import ReceptionStats


def node_id_to_str(node_id: int) -> str:
    return "!" + hex(node_id)[2:]


def format_stats(stats_list: List[ReceptionStats], node_db, html: bool = False) -> str:
    sorted_stats = sorted(stats_list, key=lambda x: x.rssi, reverse=True)
    if not sorted_stats:
        return ""
    
    stats_str = build_stats_str(sorted_stats, node_db)
    
    if html:
        return f"<small>({stats_str})</small>"
    else:
        return f"*({stats_str})*"


def build_stats_str(sorted_stats: List[ReceptionStats], node_db) -> str:
    gateway_strings = []
    for s in sorted_stats:
        gateway_name = node_db.get_node_name(s.gateway_id)
        if s.hop_count == 0:
            gateway_strings.append(f"{gateway_name} ({s.rssi}dBm/{s.snr}dB)")
        else:
            gateway_strings.append(f"{gateway_name} ({s.hop_count} hops)")
    return ', '.join(gateway_strings)


def extract_channel_name_from_topic(topic: str) -> str:
    parts = topic.split('/')
    for i, part in enumerate(parts):
        if part in ('e', 'c', 'json') and i + 1 < len(parts):
            return parts[i + 1]
    return "Unknown"


def is_emoji_only(text: str) -> bool:
    import re
    clean_text = text.strip()
    return len(clean_text) < 12 and not re.search(r'[a-zA-Z]', clean_text)
