import asyncio
import logging
from typing import Optional, TYPE_CHECKING
from nio import AsyncClient, MatrixRoom, RoomMessageText, ReactionEvent
import config

if TYPE_CHECKING:
    from bridge import MeshtasticMatrixBridge

logger = logging.getLogger(__name__)


class MatrixBot:
    def __init__(self, bridge: 'MeshtasticMatrixBridge'):
        self.bridge = bridge
        self.client: AsyncClient = AsyncClient(config.MATRIX_HOMESERVER, config.MATRIX_USER)
        self.room_id: str = config.MATRIX_ROOM_ID

    async def start(self) -> None:
        logger.info(f"Connecting to Matrix as {config.MATRIX_USER}...")

        if config.MATRIX_PASSWORD.startswith("syt_"):
            logger.info("Detected Access Token. Skipping password login.")
            self.client.access_token = config.MATRIX_PASSWORD
            self.client.user_id = config.MATRIX_USER
        else:
            resp = await self.client.login(config.MATRIX_PASSWORD)
            if hasattr(resp, 'error'):
                logger.error(f"Matrix Login failed: {resp}")
                return

        if self.room_id.startswith("#"):
            logger.info(f"Resolving room alias {self.room_id}...")
            resp = await self.client.room_resolve_alias(self.room_id)
            if hasattr(resp, 'room_id'):
                self.room_id = resp.room_id
                logger.info(f"Resolved to {self.room_id}")
            else:
                logger.error(f"Could not resolve room alias: {resp}")
                return

        logger.info("Logged in. Initial synchronization...")
        await self.client.sync(timeout=30000, full_state=True)

        self.client.add_event_callback(self._on_room_message, RoomMessageText)
        self.client.add_event_callback(self._on_reaction, ReactionEvent)

        logger.info("Matrix Bot listening...")
        asyncio.create_task(self._sync_loop())

    async def _sync_loop(self) -> None:
        try:
            await self.client.sync_forever(timeout=30000)
        except Exception as e:
            logger.error(f"Matrix sync error: {e}")

    async def stop(self) -> None:
        await self.client.close()

    async def send_message(self, text: str, html: Optional[str] = None, reply_to: Optional[str] = None) -> Optional[str]:
        content = {
            "msgtype": "m.text",
            "body": text
        }
        if html:
            content["format"] = "org.matrix.custom.html"
            content["formatted_body"] = html
        
        if reply_to:
            content["m.relates_to"] = {
                "m.in_reply_to": {
                    "event_id": reply_to
                }
            }

        resp = await self.client.room_send(
            room_id=self.room_id,
            message_type="m.room.message",
            content=content
        )
        if hasattr(resp, 'event_id'):
            return resp.event_id
        logger.error(f"Failed to send Matrix message: {resp}")
        return None

    async def edit_message(self, event_id: str, new_text: str, new_html: Optional[str] = None) -> None:
        new_content = {
            "msgtype": "m.text",
            "body": new_text
        }
        if new_html:
            new_content["format"] = "org.matrix.custom.html"
            new_content["formatted_body"] = new_html

        content = {
            "msgtype": "m.text",
            "body": new_text, # Fallback
            "m.new_content": new_content,
            "m.relates_to": {
                "rel_type": "m.replace",
                "event_id": event_id
            }
        }
        if new_html:
            content["format"] = "org.matrix.custom.html"
            content["formatted_body"] = new_html

        await self.client.room_send(
            room_id=self.room_id,
            message_type="m.room.message",
            content=content
        )
    
    async def get_display_name(self, user_id: str) -> str:
        try:
            rooms_response = await self.client.joined_rooms()
            if hasattr(rooms_response, 'rooms') and self.room_id in rooms_response.rooms:
                if self.room_id in self.client.rooms:
                    room = self.client.rooms[self.room_id]
                    if user_id in room.users:
                        display_name = room.user_name(user_id)
                        if display_name and display_name != user_id:
                            return display_name
            
            response = await self.client.get_displayname(user_id)
            if hasattr(response, 'displayname') and response.displayname:
                return response.displayname
        except Exception as e:
            logger.debug(f"Could not fetch display name for {user_id}: {e}")
        
        return user_id

    async def _on_room_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        if room.room_id != self.room_id:
            return
        
        if event.sender == self.client.user_id:
            return

        logger.info(f"Matrix message from {event.sender}: {event.body}")
        await self.bridge.handle_matrix_message(event)

    async def _on_reaction(self, room: MatrixRoom, event: ReactionEvent) -> None:
        if room.room_id != self.room_id:
            return
        
        if event.sender == self.client.user_id:
            return

        content = event.source.get('content', {})
        logger.info(f"Matrix reaction {content} from {event.sender}")
        
        event.content = content
        await self.bridge.handle_matrix_reaction(event)
