import asyncio
import logging
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from matrix_bot import MatrixBot
from mqtt_client import MqttClient
from meshtastic_interface import MeshtasticInterface
from models import ReceptionStats, MessageState
import config

logger = logging.getLogger(__name__)



class MeshtasticMatrixBridge:
    def __init__(self):
        self.message_state: Dict[int, MessageState] = {} 
        self.matrix_bot = MatrixBot(self)
        self.mqtt_client = MqttClient(self)
        self.meshtastic_interface = MeshtasticInterface(self)
        
    async def start(self):
        logger.info("Starting Meshtastic-Matrix Bridge...")
        await self.matrix_bot.start()
        self.mqtt_client.start()
        self.meshtastic_interface.start()
        
    async def stop(self):
        logger.info("Stopping Bridge...")
        self.mqtt_client.stop()
        self.meshtastic_interface.stop()
        await self.matrix_bot.stop()

    async def handle_meshtastic_message(self, packet: dict, source: str, reception_stats: ReceptionStats):
        packet_id = packet.get("id")
        sender = packet.get("fromId")
        text = packet.get("decoded", {}).get("text", "")
        
        if not text:
             return

        if packet_id in self.message_state:
            await self._handle_duplicate_message(packet_id, reception_stats)
        else:
            await self._handle_new_message(packet_id, sender, text, reception_stats)

    async def _handle_new_message(self, packet_id: int, sender: str, text: str, stats: ReceptionStats):
        stats_str = f"*(Received by: {stats.gateway_id} RSSI:{stats.rssi})*"
        full_msg = f"**{sender}**: {text}\n{stats_str}"

        matrix_event_id = await self.matrix_bot.send_message(full_msg)
        
        if matrix_event_id:
            logger.info(f"Relayed {packet_id} to Matrix as {matrix_event_id}")
            state = MessageState(
                packet_id=packet_id,
                matrix_event_id=matrix_event_id,
                original_text=text,
                sender=sender,
                reception_list=[stats]
            )
            self.message_state[packet_id] = state

    async def _handle_duplicate_message(self, packet_id: int, new_stats: ReceptionStats):
        state = self.message_state[packet_id]
        if any(s.gateway_id == new_stats.gateway_id for s in state.reception_list):
            return 

        state.reception_list.append(new_stats)
        state.last_update = time.time()
        await self._update_matrix_message(state)

    async def _update_matrix_message(self, state: MessageState):
        sorted_stats = sorted(state.reception_list, key=lambda x: x.rssi, reverse=True)
        gateway_strings = [f"{s.gateway_id} ({s.rssi}dB)" for s in sorted_stats]
        stats_str = ", ".join(gateway_strings)
        new_content = f"**{state.sender}**: {state.original_text}\n*(Received by: {stats_str})*"
        await self.matrix_bot.edit_message(state.matrix_event_id, new_content)

    async def handle_matrix_message(self, event):
        sender = event.sender
        content = event.body
        full_message = f"[{sender}]: {content}"
        
        max_len = 200
        encoded = full_message.encode('utf-8')
        
        if len(encoded) > max_len:
            parts = []
            while encoded:
                parts.append(encoded[:max_len])
                encoded = encoded[max_len:]
                
            for i, part in enumerate(parts):
                text_part = part.decode('utf-8', errors='ignore')
                prefix = f"({i+1}/{len(parts)}) "
                self.meshtastic_interface.send_text(f"{prefix}{text_part}")
                await asyncio.sleep(0.5)
        else:
            self.meshtastic_interface.send_text(full_message)

    async def handle_matrix_reaction(self, event):
        # In matrix-nio, the event object handles content differently depending on event type.
        # But usually raw content is in event.source['content'] or event.content
        # RoomReactionEvent has .content
        relates_to = event.content.get("m.relates_to", {})
        event_id = relates_to.get("event_id")
        key = relates_to.get("key")
        
        if not event_id or not key:
            return

        target_packet_id = None
        for pid, state in self.message_state.items():
            if state.matrix_event_id == event_id:
                target_packet_id = pid
                break
        
        if target_packet_id:
            logger.info(f"Forwarding reaction {key} to mesh for packet {target_packet_id}")
            self.meshtastic_interface.send_tapback(target_packet_id, key)
