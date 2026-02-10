import asyncio
import logging
import time
import re
from typing import Dict, Optional

from src.adapters.matrix_bot import MatrixBot
from src.adapters.mqtt_client import MqttClient
from src.adapters.meshtastic_interface import MeshtasticInterface
from src.models import ReceptionStats, MessageState
from src.database.node_database import NodeDatabase
from src.constants import REACTION_APP, MAX_MESSAGE_LENGTH
from src.utils import format_stats, is_emoji_only
from src import config

logger = logging.getLogger(__name__)



class MeshtasticMatrixBridge:
    def __init__(self):
        self.loop = asyncio.get_event_loop()
        self.node_db = NodeDatabase()
        self.message_state: Dict[int, MessageState] = self.node_db.load_message_states()
        self.last_packet_id: Optional[int] = self._restore_last_packet_id()
        self.processing_packets: Dict[int, asyncio.Event] = {}
        self.matrix_bot = MatrixBot(self)
        self.mqtt_client = MqttClient(self)
        self.meshtastic_interface = MeshtasticInterface(self)
        self._cleanup_task = None
        
        # Configuration for memory management
        self.MESSAGE_STATE_MAX_AGE = 86400  # 24 hours in seconds
        self.MESSAGE_STATE_MAX_SIZE = 10000  # Maximum number of message states to keep
        self.CLEANUP_INTERVAL = 3600  # Run cleanup every hour
    
    def _restore_last_packet_id(self) -> Optional[int]:
        if not self.message_state:
            return None
        sorted_states = sorted(
            self.message_state.values(), 
            key=lambda s: s.last_update, 
            reverse=True
        )
        last_id = sorted_states[0].packet_id
        logger.info(f"Restored last_packet_id: {last_id}")
        return last_id
        
    async def start(self):
        logger.info("Starting Meshtastic-Matrix Bridge...")
        await self.matrix_bot.start()
        self.mqtt_client.start()
        self.meshtastic_interface.start()
        
        # Start periodic cleanup task
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        logger.info("Started periodic cleanup task")
        
    async def stop(self):
        logger.info("Stopping Bridge...")
        
        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        self.mqtt_client.stop()
        self.meshtastic_interface.stop()
        await self.matrix_bot.stop()

    async def handle_meshtastic_message(self, packet: dict, source: str, reception_stats: ReceptionStats):
        packet_id = packet.get("id")
        sender = packet.get("fromId")
        decoded = packet.get("decoded", {})
        portnum = decoded.get("portnum")
        
        text = self._extract_text(decoded, portnum)
        reply_id = self._find_reply_id(packet, decoded, packet_id, text, portnum)
        
        channel = str(packet.get("channel", 0))
        channel_name = packet.get("channel_name", "Unknown")
        
        logger.info(f"Processing Packet {packet_id} from {sender} on channel {channel} ({channel_name}). Port={portnum}, Text='{text}', Found ReplyID={reply_id}")
        
        if not self._should_process_message(packet_id, sender, text, reply_id, channel, channel_name, portnum):
            return

        if packet_id in self.processing_packets:
            logger.info(f"Packet {packet_id} is currently processing, waiting...")
            await self.processing_packets[packet_id].wait()

        if packet_id in self.message_state:
            await self._handle_duplicate_message(packet_id, reception_stats)
        elif reply_id and reply_id in self.message_state:
            await self._handle_reply_message(packet_id, sender, text, reply_id, reception_stats, portnum)
        else:
            await self._handle_new_message(packet_id, sender, text, reception_stats)
    
    def _extract_text(self, decoded: dict, portnum: int) -> str:
        text = str(decoded.get("text", decoded.get("emoji", "") or ""))
        
        if not text and portnum == REACTION_APP:
            payload = decoded.get("payload")
            if isinstance(payload, bytes):
                try:
                    text = payload.decode("utf-8")
                except Exception:
                    text = ""
            elif isinstance(payload, str):
                text = payload
        
        return text
    
    def _find_reply_id(self, packet: dict, decoded: dict, packet_id: int, text: str, portnum: int) -> int:
        reply_id = self._search_reply_fields(packet, decoded)
        
        if reply_id == 0:
            reply_id = self._deep_search_reply_id(packet, decoded, packet_id)
        
        if reply_id == 0:
            reply_id = self._parse_legacy_reaction(text, packet.get("fromId"))
        
        if reply_id == 0:
            reply_id = self._heuristic_reply_id(text, portnum, packet_id)
        
        return reply_id
    
    def _search_reply_fields(self, packet: dict, decoded: dict) -> int:
        search_objs = [decoded, packet]
        search_keys = ["replyId", "reply_id", "requestId", "request_id", "replyTo", "reply_to"]
        
        for obj in search_objs:
            if not isinstance(obj, dict):
                continue
            for key in search_keys:
                val = obj.get(key)
                if val:
                    try:
                        potential_id = int(val)
                        if potential_id != 0:
                            return potential_id
                    except (ValueError, TypeError):
                        pass
        return 0
    
    def _deep_search_reply_id(self, packet: dict, decoded: dict, packet_id: int) -> int:
        for obj in [decoded, packet]:
            if not isinstance(obj, dict):
                continue
            for k, v in obj.items():
                try:
                    v_int = int(v)
                    if v_int != 0 and v_int in self.message_state and v_int != packet_id:
                        logger.info(f"Deep Linkage Search found match: field '{k}' contains known packet ID {v_int}")
                        return v_int
                except (ValueError, TypeError):
                    continue
        return 0
    
    def _parse_legacy_reaction(self, text: str, sender: str) -> int:
        reaction_match = re.match(r"^\[Reaction to (\d+)\]: (.+)$", text)
        if not reaction_match:
            return 0
        
        target_id_str, emoji = reaction_match.groups()
        my_node_id = getattr(self.meshtastic_interface, 'node_id', None)
        
        if my_node_id and sender == my_node_id:
            logger.info(f"Ignoring own reaction echo for {target_id_str}")
            return 0
        
        try:
            reply_id = int(target_id_str)
            logger.info(f"Parsed legacy text reaction from {sender} to {reply_id}: {emoji}")
            return reply_id
        except ValueError:
            return 0
    
    def _heuristic_reply_id(self, text: str, portnum: int, packet_id: int) -> int:
        clean_text = text.strip()
        is_emoji_candidate = is_emoji_only(clean_text)
        
        if (is_emoji_candidate or portnum == REACTION_APP) and self.last_packet_id and self.last_packet_id != packet_id:
            logger.info(f"Heuristic: Treating orphan '{clean_text}' (Port={portnum}) as reaction to last packet {self.last_packet_id}")
            return self.last_packet_id
        
        return 0
    
    def _should_process_message(self, packet_id: int, sender: str, text: str, reply_id: int, channel: str, channel_name: str, portnum: int) -> bool:
        allowed_channels = config.MESHTASTIC_CHANNELS
        if channel not in allowed_channels and channel_name not in allowed_channels:
            logger.info(f"Ignoring packet {packet_id} from channel {channel} ({channel_name}) (Allowed: {allowed_channels})")
            return False

        if not text:
            logger.debug(f"Ignoring empty packet {packet_id} (Port={portnum})")
            return False
        
        if reply_id == 0 and len(text) > 0 and (len(text) < 12 or portnum == REACTION_APP):
            logger.debug(f"Reaction linkage failed for packet {packet_id}")
        
        return True

    async def _handle_new_message(self, packet_id: int, sender: str, text: str, stats: ReceptionStats):
        # Update last_packet_id for context
        self.last_packet_id = packet_id
        
        # Mark as processing
        event = asyncio.Event()
        self.processing_packets[packet_id] = event

        try:
            sender_name = self.node_db.get_node_name(sender)
            
            stats_str = format_stats([stats], self.node_db, html=False)
            stats_html = format_stats([stats], self.node_db, html=True)
            
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
    
    async def _handle_reply_message(self, packet_id: int, sender: str, text: str, reply_id: int, stats: ReceptionStats, portnum: Optional[int] = None):
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
            
            clean_text = text.strip()
            is_reaction_port = (portnum == REACTION_APP)
            is_emoji_candidate = is_emoji_only(clean_text)
            is_emoji_reaction = is_reaction_port or is_emoji_candidate
            
            logger.debug(f"Reply Analysis: text='{clean_text}', port={portnum}, is_emoji_reaction={is_emoji_reaction}")

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
                await self._update_matrix_message(original_state)
                self.node_db.save_message_state(original_state)
                logger.info(f"Added reaction {packet_id} to {reply_id}")

            else:
                stats_str = format_stats([stats], self.node_db, html=False)
                stats_html = format_stats([stats], self.node_db, html=True)
                
                # Construct Reply Fallback (Quoting)
                # Text fallback
                original_sender_name = self.node_db.get_node_name(original_state.sender)
                original_short = (original_state.original_text[:50] + '...') if len(original_state.original_text) > 50 else original_state.original_text
                
                quote_text = f" > <{original_sender_name}> {original_short}\n\n"
                
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
                        reception_list=[stats],
                        parent_packet_id=reply_id
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
        
        # If this message is a reaction (has parent but NO matrix_event_id), update parent.
        # Otherwise, update this message itself.
        if state.parent_packet_id and not state.matrix_event_id:
            parent_state = self.message_state.get(state.parent_packet_id)
            if parent_state:
                await self._update_matrix_message(parent_state)
            else:
                logger.warning(f"Parent state {state.parent_packet_id} not found for reaction {packet_id}")
        else:
            await self._update_matrix_message(state)

    async def _update_matrix_message(self, state: MessageState):
        sender_name = self.node_db.get_node_name(state.sender)
        
        stats_str = format_stats(state.reception_list, self.node_db, html=False)
        stats_html = format_stats(state.reception_list, self.node_db, html=True)
        
        # Reconstruct Quote if it's a True Reply
        quote_text = ""
        quote_html = ""
        if state.parent_packet_id and state.matrix_event_id:
            parent_state = self.message_state.get(state.parent_packet_id)
            if parent_state:
                parent_sender_name = self.node_db.get_node_name(parent_state.sender)
                parent_short = (parent_state.original_text[:50] + '...') if len(parent_state.original_text) > 50 else parent_state.original_text
                
                quote_text = f"> <{parent_sender_name}> {parent_short}\n\n"
                
                room_id = self.matrix_bot.room_id
                orig_evt_id = parent_state.matrix_event_id
                quote_link = f'<a href="https://matrix.to/#/{room_id}/{orig_evt_id}">In reply to</a>'
                quote_user = f'<a href="https://matrix.to/#/{parent_sender_name}">{parent_sender_name}</a>'
                quote_html = f'<mx-reply><blockquote>{quote_link} {quote_user}<br>{parent_short}</blockquote></mx-reply>'

        # Prepare Replies (Reactions attached to this message)
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
                        r_stats = format_stats(r_state.reception_list, self.node_db, html=False)
                        r_stats_html = format_stats(r_state.reception_list, self.node_db, html=True)
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
            new_content = f"{quote_text}[{sender_name}]: {state.original_text}\n{stats_str}{reply_block}"
            new_html = f"{quote_html}<b>[{sender_name}]</b>: {state.original_text}<br>{stats_html}{reply_block_html}"
            
            if state.matrix_event_id:
                await self.matrix_bot.edit_message(state.matrix_event_id, new_content, new_html)

    async def handle_matrix_message(self, event):
        # Get the display name for the sender
        sender_name = await self.matrix_bot.get_display_name(event.sender)
        content = event.body
        
        # Handle Matrix Reply fallback/logic
        reply_to_event_id = event.source.get('content', {}).get("m.relates_to", {}).get("m.in_reply_to", {}).get("event_id")
        target_packet_id = None
        if reply_to_event_id:
            # Strip Matrix fallback from body
            # The fallback usually starts with "> <@user:homeserver> quoted text" followed by \n\n
            parts = content.split("\n\n", 1)
            if len(parts) > 1 and parts[0].startswith(">"):
                content = parts[1]
                logger.debug(f"Stripped Matrix reply fallback. Clean text: {content}")
            
            # Try to resolve target Mesh packet ID
            for pid, state in self.message_state.items():
                if state.matrix_event_id == reply_to_event_id:
                    target_packet_id = pid
                    logger.info(f"Matrix message is a reply to Mesh packet {target_packet_id}")
                    break

        full_message = f"[{sender_name}]: {content}"
        encoded = full_message.encode('utf-8')
        
        if len(encoded) > MAX_MESSAGE_LENGTH:
            parts = []
            while encoded:
                parts.append(encoded[:MAX_MESSAGE_LENGTH])
                encoded = encoded[MAX_MESSAGE_LENGTH:]
                
            for i, part in enumerate(parts):
                text_part = part.decode('utf-8', errors='ignore')
                prefix = f"({i+1}/{len(parts)}) "
                # We only attach replyId to the first part to avoid mesh confusion
                part_reply_id = target_packet_id if i == 0 else None
                self.meshtastic_interface.send_text(f"{prefix}{text_part}", 
                                                   channel_idx=config.MESHTASTIC_CHANNEL_IDX,
                                                   reply_id=part_reply_id)
                await asyncio.sleep(0.5)
        else:
             packet = self.meshtastic_interface.send_text(full_message, 
                                                        channel_idx=config.MESHTASTIC_CHANNEL_IDX,
                                                        reply_id=target_packet_id)
             
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
            self.meshtastic_interface.send_tapback(target_packet_id, key, channel_idx=config.MESHTASTIC_CHANNEL_IDX)

    async def _periodic_cleanup(self):
        """Periodically clean up old message states to prevent memory leaks."""
        while True:
            try:
                await asyncio.sleep(self.CLEANUP_INTERVAL)
                await self._cleanup_old_messages()
            except asyncio.CancelledError:
                logger.info("Cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}", exc_info=True)
    
    async def _cleanup_old_messages(self):
        """Remove old message states that are no longer needed."""
        try:
            current_time = time.time()
            initial_count = len(self.message_state)
            
            # Remove messages older than MESSAGE_STATE_MAX_AGE
            to_remove = []
            for packet_id, state in self.message_state.items():
                age = current_time - state.last_update
                if age > self.MESSAGE_STATE_MAX_AGE:
                    to_remove.append(packet_id)
            
            for packet_id in to_remove:
                del self.message_state[packet_id]
            
            # If still too many messages, remove oldest ones
            if len(self.message_state) > self.MESSAGE_STATE_MAX_SIZE:
                # Sort by last_update and keep only the newest MESSAGE_STATE_MAX_SIZE
                sorted_states = sorted(
                    self.message_state.items(),
                    key=lambda x: x[1].last_update,
                    reverse=True
                )
                self.message_state = dict(sorted_states[:self.MESSAGE_STATE_MAX_SIZE])
            
            removed_count = initial_count - len(self.message_state)
            if removed_count > 0:
                logger.info(f"Cleanup: Removed {removed_count} old message states. {len(self.message_state)} remaining.")
                
        except Exception as e:
            logger.error(f"Error during message cleanup: {e}", exc_info=True)
