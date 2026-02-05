import asyncio
import logging
from typing import Optional, Callable
from nio import AsyncClient, MatrixRoom, RoomMessageText, RoomMessageNotice, Event, ReactionEvent
import config

logger = logging.getLogger(__name__)

class MatrixBot:
    def __init__(self, bridge):
        self.bridge = bridge
        self.client = AsyncClient(config.MATRIX_HOMESERVER, config.MATRIX_USER)
        self.room_id = config.MATRIX_ROOM_ID

    async def start(self):
        logger.info(f"Connecting to Matrix as {config.MATRIX_USER}...")

        # Check if password is actually an access token
        if config.MATRIX_PASSWORD.startswith("syt_"):
            logger.info("Detected Access Token. Skipping password login.")
            self.client.access_token = config.MATRIX_PASSWORD
            self.client.user_id = config.MATRIX_USER
        else:
            resp = await self.client.login(config.MATRIX_PASSWORD)
            
            logger.info(f"DEBUG: Login response type: {type(resp)}")
            if hasattr(resp, 'error'):
                 logger.error(f"Matrix Login failed: {resp}")
                 return

        # Resolve Room Alias if needed
        if self.room_id.startswith("#"):
            logger.info(f"Resolving room alias {self.room_id}...")
            resp = await self.client.room_resolve_alias(self.room_id)
            if hasattr(resp, 'room_id'):
                self.room_id = resp.room_id
                logger.info(f"Resolved to {self.room_id}")
            else:
                logger.error(f"Could not resolve room alias: {resp}")
                return

        logger.info(f"Logged in. Initial synchronization...")
        await self.client.sync(timeout=30000, full_state=True) # Initial sync

        self.client.add_event_callback(self._on_room_message, RoomMessageText)
        self.client.add_event_callback(self._on_reaction, ReactionEvent)

        logger.info("Matrix Bot listening...")
        # Start sync loop in background
        asyncio.create_task(self._sync_loop())

    async def _sync_loop(self):
        try:
            await self.client.sync_forever(timeout=30000)
        except Exception as e:
            logger.error(f"Matrix sync error: {e}")

    async def stop(self):
        await self.client.close()

    async def send_message(self, text: str) -> Optional[str]:
        resp = await self.client.room_send(
            room_id=self.room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": text
            }
        )
        if hasattr(resp, 'event_id'):
            return resp.event_id
        logger.error(f"Failed to send Matrix message: {resp}")
        return None

    async def edit_message(self, event_id: str, new_text: str):
        # Matrix edit is a new event with "m.relates_to"
        content = {
            "msgtype": "m.text",
            "body": new_text, # Fallback
            "m.new_content": {
                "msgtype": "m.text",
                "body": new_text
            },
            "m.relates_to": {
                "rel_type": "m.replace",
                "event_id": event_id
            }
        }
        await self.client.room_send(
            room_id=self.room_id,
            message_type="m.room.message",
            content=content
        )
    
    async def get_display_name(self, user_id: str) -> str:
        """Get the display name for a user in the current room.
        
        Prioritizes room-specific nicknames (set via /myroomnick) over global display names.
        Falls back to the user_id if display name is not available.
        """
        try:
            # First, try to get the room-specific display name from room members
            # This includes nicknames set via /myroomnick
            rooms_response = await self.client.joined_rooms()
            if hasattr(rooms_response, 'rooms') and self.room_id in rooms_response.rooms:
                # Get room members to access room-specific display names
                # We need to check the synced room data
                if self.room_id in self.client.rooms:
                    room = self.client.rooms[self.room_id]
                    # Check if user is in the room and get their display name
                    if user_id in room.users:
                        display_name = room.user_name(user_id)
                        if display_name and display_name != user_id:
                            return display_name
            
            # Fallback to global display name
            response = await self.client.get_displayname(user_id)
            if hasattr(response, 'displayname') and response.displayname:
                return response.displayname
        except Exception as e:
            logger.debug(f"Could not fetch display name for {user_id}: {e}")
        
        # Final fallback to user_id
        return user_id

    async def _on_room_message(self, room: MatrixRoom, event: RoomMessageText):
        if room.room_id != self.room_id:
            return
        
        # Ignore own messages
        if event.sender == self.client.user_id:
            return

        # Handle message forwarding to Mesh
        logger.info(f"Matrix message from {event.sender}: {event.body}")
        await self.bridge.handle_matrix_message(event)

    async def _on_reaction(self, room: MatrixRoom, event: ReactionEvent):
        if room.room_id != self.room_id:
            return
        
        if event.sender == self.client.user_id:
            return

        logger.info(f"Matrix reaction {event.content} from {event.sender}")
        await self.bridge.handle_matrix_reaction(event)
