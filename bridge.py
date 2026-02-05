import asyncio
import logging
import time
import re
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from matrix_bot import MatrixBot
from mqtt_client import MqttClient
from meshtastic_interface import MeshtasticInterface
from models import ReceptionStats, MessageState
from node_database import NodeDatabase
import config

logger = logging.getLogger(__name__)



class MeshtasticMatrixBridge:
    def __init__(self):
        self.node_db = NodeDatabase()
        self.message_state: Dict[int, MessageState] = self.node_db.load_message_states()
        
        # Determine last packet ID based on last_update timestamp
        self.last_packet_id: Optional[int] = None
        if self.message_state:
            # Sort states by last_update descending
            sorted_states = sorted(self.message_state.values(), key=lambda s: s.last_update, reverse=True)
            self.last_packet_id = sorted_states[0].packet_id
            logger.info(f"Restored last_packet_id: {self.last_packet_id}")

        self.processing_packets: Dict[int, asyncio.Event] = {} # Track packets being processed
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
        decoded = packet.get("decoded", {})
        text = decoded.get("text", "")
        reply_id = decoded.get("replyId", 0)
        
        logger.info(f"Processing Packet {packet_id} from {sender}. Text='{text}', ReplyID={reply_id}, Port={packet.get('decoded', {}).get('portnum')}")
        logger.debug(f"Full Decoded Packet: {decoded}")
        
        if not text:
             return

        # Check for "[Reaction to ID]: Emoji" pattern (legacy/bridge reactions)
        reaction_match = re.match(r"^\[Reaction to (\d+)\]: (.+)$", text)
        if reaction_match:
            target_id_str, emoji = reaction_match.groups()
            
            my_node_id = getattr(self.meshtastic_interface, 'node_id', None)
            
            if my_node_id and sender == my_node_id:
                logger.info(f"Ignoring own reaction echo for {target_id_str}")
                return
            
            try:
                reply_id = int(target_id_str)
                text = emoji
                logger.info(f"Parsed text reaction from {sender} to {reply_id}: {emoji}")
            except ValueError:
                pass
        
        # HEURISTIC: If reply_id is 0 but text looks like an emoji/short-ack,
        # attach it to the LAST message seen.
        clean_text = text.strip()
        is_emoji_candidate = len(clean_text) < 12
        if reply_id == 0 and is_emoji_candidate and self.last_packet_id and self.last_packet_id != packet_id:
            logger.info(f"Heuristic: Treating orphan '{clean_text}' as reaction to last packet {self.last_packet_id}")
            reply_id = self.last_packet_id

        # Check race condition / pending processing
        if packet_id in self.processing_packets:
            logger.info(f"Packet {packet_id} is currently processing, waiting...")
            await self.processing_packets[packet_id].wait()
            # After wait, fall through to check message_state

        # Check if this is a reply to an existing message (or updated via heuristic)
        if reply_id and reply_id in self.message_state:
            await self._handle_reply_message(packet_id, sender, text, reply_id, reception_stats)
        elif packet_id in self.message_state:
            await self._handle_duplicate_message(packet_id, reception_stats)
        else:
            await self._handle_new_message(packet_id, sender, text, reception_stats)

    async def _handle_new_message(self, packet_id: int, sender: str, text: str, stats: ReceptionStats):
        # Update last_packet_id for context
        self.last_packet_id = packet_id
        
        # Mark as processing
        event = asyncio.Event()
        self.processing_packets[packet_id] = event

        try:
            # Resolve sender name from database
            sender_name = self.node_db.get_node_name(sender)
            
            # Format stats
            stats_str = self._format_stats([stats])
            stats_html = self._format_stats_html([stats])
            
            full_msg = f"[{sender_name}]: {text}\n{stats_str}"
            formatted_msg = f"<b>[{sender_name}]</b>: {text}<br>{stats_html}"

            matrix_event_id = await self.matrix_bot.send_message(full_msg, formatted_msg)
            
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
                self.node_db.save_message_state(state)
        finally:
            # Clear processing state
            if packet_id in self.processing_packets:
                del self.processing_packets[packet_id]
            event.set()
    
    async def _handle_reply_message(self, packet_id: int, sender: str, text: str, reply_id: int, stats: ReceptionStats):
        """Handle a message that is a reply to another message."""
        # Mark as processing (even repliers might get duplicated from LAN/MQTT)
        event = asyncio.Event()
        self.processing_packets[packet_id] = event

        try:
            original_state = self.message_state.get(reply_id)
            if not original_state:
                # Original message not found, treat as new message
                await self._handle_new_message(packet_id, sender, text, stats)
                return
            
            sender_name = self.node_db.get_node_name(sender)
            
            # Heuristic: If text is short (likely emoji/reaction), append to original.
            # Otherwise, send as a Matrix Reply.
            clean_text = text.strip()
            # Emojis can be multi-byte (up to 8-10 bytes for complex flags/families)
            # A strict limit of 5 is dangerous. Let's try 12 "chars".
            is_emoji_reaction = len(clean_text) < 12 
            
            logger.debug(f"Reply Analysis: text='{clean_text}', len={len(clean_text)}, is_emoji={is_emoji_reaction}")

            if is_emoji_reaction:
                 # Logic for "Edit Original" (Appended Text)
                 # New Logic: Create a MessageState for the reply to support de-duplication/aggregation
                reply_state = MessageState(
                    packet_id=packet_id,
                    matrix_event_id=None,
                    original_text=clean_text,
                    sender=sender,
                    reception_list=[stats],
                    parent_packet_id=reply_id,
                    last_update=time.time()
                )
                self.message_state[packet_id] = reply_state
                self.node_db.save_message_state(reply_state)

                if not hasattr(original_state, 'replies'):
                    original_state.replies = []
                
                # Check if we already have this packet_id in replies (shouldn't happen for new, but for safety)
                if packet_id not in original_state.replies:
                    original_state.replies.append(packet_id)
                
                # Update the Matrix message to include the reply (edit)
                await self._update_message_with_replies(original_state)
                self.node_db.save_message_state(original_state)
                logger.info(f"Added reaction {packet_id} to {reply_id}")

            else:
                # Logic for "True Reply" (New Matrix Message)
                stats_str = self._format_stats([stats])
                stats_html = self._format_stats_html([stats])
                
                # Construct Reply Fallback (Quoting)
                # Text fallback
                original_sender_name = self.node_db.get_node_name(original_state.sender)
                original_short = (original_state.original_text[:50] + '...') if len(original_state.original_text) > 50 else original_state.original_text
                
                quote_text = f"> <{original_sender_name}> {original_short}\n\n"
                
                # HTML fallback
                room_id = self.matrix_bot.room_id
                orig_evt_id = original_state.matrix_event_id
                # Note: valid link format helps clients jump
                quote_link = f'<a href="https://matrix.to/#/{room_id}/{orig_evt_id}">In reply to</a>'
                quote_user = f'<a href="https://matrix.to/#/{original_sender_name}">{original_sender_name}</a>'
                quote_html = f'<mx-reply><blockquote>{quote_link} {quote_user}<br>{original_short}</blockquote></mx-reply>'

                full_msg = f"{quote_text}[{sender_name}]: {text}\n{stats_str}"
                formatted_msg = f"{quote_html}<b>[{sender_name}]</b>: {text}<br>{stats_html}"
                
                matrix_event_id = await self.matrix_bot.send_message(full_msg, formatted_msg, reply_to=original_state.matrix_event_id)
                
                if matrix_event_id:
                     state = MessageState(
                        packet_id=packet_id,
                        matrix_event_id=matrix_event_id,
                        original_text=text,
                        sender=sender,
                        reception_list=[stats]
                    )
                     self.message_state[packet_id] = state
                     self.node_db.save_message_state(state)

        finally:
            if packet_id in self.processing_packets:
                del self.processing_packets[packet_id]
            event.set()

    async def _handle_duplicate_message(self, packet_id: int, new_stats: ReceptionStats):
        state = self.message_state[packet_id]
        if any(s.gateway_id == new_stats.gateway_id for s in state.reception_list):
            return 

        state.reception_list.append(new_stats)
        state.last_update = time.time()
        self.node_db.save_message_state(state)
        
        # If this message is a child (reaction), update the parent
        if state.parent_packet_id:
            parent_state = self.message_state.get(state.parent_packet_id)
            if parent_state:
                await self._update_matrix_message(parent_state)
            else:
                logger.warning(f"Parent state {state.parent_packet_id} not found for child {packet_id}")
        else:
            await self._update_matrix_message(state)

    async def _update_matrix_message(self, state: MessageState):
        # Resolve sender name from database
        sender_name = self.node_db.get_node_name(state.sender)
        
        stats_str = self._format_stats(state.reception_list)
        stats_html = self._format_stats_html(state.reception_list)
        
        # Prepare Replies
        reply_block = ""
        reply_block_html = ""
        if hasattr(state, 'replies') and state.replies:
            reply_lines = []
            reply_lines_html = []
            
            for reply_item in state.replies:
                if isinstance(reply_item, int):
                    # It's a Packet ID pointing to a Reaction State
                    r_state = self.message_state.get(reply_item)
                    if r_state:
                        r_sender = self.node_db.get_node_name(r_state.sender)
                        r_stats = self._format_stats(r_state.reception_list)
                        r_stats_html = self._format_stats_html(r_state.reception_list)
                        # "  ↳ [Sender]: Text (Stats)"
                        reply_lines.append(f"  ↳ [{r_sender}]: {r_state.original_text} {r_stats}")
                        reply_lines_html.append(f"&nbsp;&nbsp;↳ [{r_sender}]: {r_state.original_text} {r_stats_html}")
                else:
                    # Legacy String
                    reply_lines.append(str(reply_item))
                    reply_lines_html.append(str(reply_item).replace('<','&lt;'))

            if reply_lines:
                reply_block = "\n" + "\n".join(reply_lines)
                reply_block_html = "<br>" + "<br>".join(reply_lines_html)

        # Render Logic
        if state.render_only_stats:
            # Compact Mode: Only show stats and replies
            # We don't repeat the sender name/text because it's attached to the user's message
            # But we might want to be clear? 
            # "*(Received by: ...)*"
            
            new_content = f"{stats_str}{reply_block}"
            new_html = f"{stats_html}{reply_block_html}"
            
            if not state.matrix_event_id:
                # We haven't posted the stats message yet. Create it now.
                # User requested to remove "in reply to" for cleaner look, relying on proximity
                
                event_id = await self.matrix_bot.send_message(new_content, new_html)
                if event_id:
                    state.matrix_event_id = event_id
                    self.node_db.save_message_state(state)
            else:
                # Edit existing stats message
                await self.matrix_bot.edit_message(state.matrix_event_id, new_content, new_html)

        else:
            # Standard Mode: Full message relay
            new_content = f"[{sender_name}]: {state.original_text}\n{stats_str}{reply_block}"
            new_html = f"<b>[{sender_name}]</b>: {state.original_text}<br>{stats_html}{reply_block_html}"
            
            if state.matrix_event_id:
                await self.matrix_bot.edit_message(state.matrix_event_id, new_content, new_html)
    
    async def _update_message_with_replies(self, state: MessageState):
        """Update a Matrix message to include replies."""
        await self._update_matrix_message(state)
    
    def _format_stats(self, stats_list: List[ReceptionStats]) -> str:
        """Format reception statistics (Text)."""
        sorted_stats = sorted(stats_list, key=lambda x: x.rssi, reverse=True)
        if not sorted_stats:
            return ""
        return f"*({self._build_stats_str(sorted_stats)})*"

    def _format_stats_html(self, stats_list: List[ReceptionStats]) -> str:
        """Format reception statistics (HTML)."""
        sorted_stats = sorted(stats_list, key=lambda x: x.rssi, reverse=True)
        if not sorted_stats:
             return ""
        return f"<small>({self._build_stats_str(sorted_stats)})</small>"

    def _build_stats_str(self, sorted_stats) -> str:
        gateway_strings = []
        for s in sorted_stats:
            gateway_name = self.node_db.get_node_name(s.gateway_id)
            if s.hop_count == 0:
                gateway_strings.append(f"{gateway_name} ({s.rssi}dBm/{s.snr}dB)")
            else:
                gateway_strings.append(f"{gateway_name} ({s.hop_count} hops)")
        return ', '.join(gateway_strings)

    async def handle_matrix_message(self, event):
        # Get the display name for the sender
        sender_name = await self.matrix_bot.get_display_name(event.sender)
        content = event.body
        full_message = f"[{sender_name}]: {content}"
        
        # Handle chunking if needed (skipped here for brevity/compactness logic focus)
        # But if we did chunking, we probably only track the last one or something?
        # Actually meshtastic sendText handles splitting internally usually? 
        # No, the bridge code handled splitting manually before (lines 152-165 in original).
        # We need to preserve splitting logic but maybe only track the "main" one?
        # Or just track the single message if small.
        
        # Let's check original splitting logic
        max_len = 200
        encoded = full_message.encode('utf-8')
        
        if len(encoded) > max_len:
            # Splitting case
            parts = []
            while encoded:
                parts.append(encoded[:max_len])
                encoded = encoded[max_len:]
                
            for i, part in enumerate(parts):
                text_part = part.decode('utf-8', errors='ignore')
                prefix = f"({i+1}/{len(parts)}) "
                # We won't track split messages for now to avoid complexity in this step
                self.meshtastic_interface.send_text(f"{prefix}{text_part}")
                await asyncio.sleep(0.5)
        else:
             packet = self.meshtastic_interface.send_text(full_message)
             
             # Normal case - Track this!
             if packet and hasattr(packet, 'id'):
                 packet_id = packet.id
                 logger.info(f"Tracking Matrix-originated message {packet_id}")
                 
                 state = MessageState(
                     packet_id=packet_id,
                     matrix_event_id=None, # Will be set when stats arrive
                     original_text=content, # User text
                     sender=event.sender, # Matrix ID
                     render_only_stats=True,
                     related_event_id=event.event_id
                 )
                 self.message_state[packet_id] = state
                 self.node_db.save_message_state(state)
    
    async def handle_node_info(self, node_id: str, short_name: Optional[str] = None, long_name: Optional[str] = None):
        """Handle NODEINFO packets to update the node database."""
        self.node_db.update_node(node_id, short_name, long_name)
        logger.info(f"Updated node info for {node_id}: {short_name or long_name}")

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
