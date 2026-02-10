import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from matrix_bot import MatrixBot
from nio import MatrixRoom, RoomMessageText, ReactionEvent, LoginResponse, JoinedRoomsResponse, RoomResolveAliasResponse


class TestMatrixBot(unittest.TestCase):
    def setUp(self):
        self.bridge = MagicMock()
        self.bridge.handle_matrix_message = AsyncMock()
        self.bridge.handle_matrix_reaction = AsyncMock()
        
    @patch('matrix_bot.AsyncClient')
    def test_initialization(self, mock_client):
        with patch('config.MATRIX_HOMESERVER', 'https://matrix.org'):
            with patch('config.MATRIX_USER', '@user:matrix.org'):
                bot = MatrixBot(self.bridge)
                
                self.assertEqual(bot.bridge, self.bridge)
                mock_client.assert_called_once()

    @patch('matrix_bot.AsyncClient')
    def test_start_with_password(self, mock_client):
        async def run():
            mock_instance = AsyncMock()
            mock_client.return_value = mock_instance
            
            # Mock successful login
            login_response = MagicMock(spec=LoginResponse)
            login_response.access_token = "test_token"
            mock_instance.login.return_value = login_response
            
            # Mock room resolution
            with patch('config.MATRIX_HOMESERVER', 'https://matrix.org'):
                with patch('config.MATRIX_USER', '@user:matrix.org'):
                    with patch('config.MATRIX_PASSWORD', 'password'):
                        with patch('config.MATRIX_ROOM_ID', '#room:matrix.org'):
                            bot = MatrixBot(self.bridge)
                            bot.client = mock_instance
                            bot.room_id = '!resolved:matrix.org'
                            
                            # Don't actually start sync loop
                            with patch.object(bot, '_sync_loop', new_callable=AsyncMock):
                                await bot.start()
                            
                            mock_instance.login.assert_called_once()
        
        asyncio.run(run())

    @patch('matrix_bot.AsyncClient')
    def test_send_message(self, mock_client):
        async def run():
            mock_instance = AsyncMock()
            mock_client.return_value = mock_instance
            
            # Mock send response
            mock_response = MagicMock()
            mock_response.event_id = "$event123"
            mock_instance.room_send.return_value = mock_response
            
            with patch('config.MATRIX_HOMESERVER', 'https://matrix.org'):
                with patch('config.MATRIX_USER', '@user:matrix.org'):
                    bot = MatrixBot(self.bridge)
                    bot.client = mock_instance
                    bot.room_id = '!room:matrix.org'
                    
                    event_id = await bot.send_message("Test message", "<b>Test message</b>")
                    
                    self.assertEqual(event_id, "$event123")
                    mock_instance.room_send.assert_called_once()
        
        asyncio.run(run())

    @patch('matrix_bot.AsyncClient')
    def test_send_message_with_reply(self, mock_client):
        async def run():
            mock_instance = AsyncMock()
            mock_client.return_value = mock_instance
            
            mock_response = MagicMock()
            mock_response.event_id = "$event456"
            mock_instance.room_send.return_value = mock_response
            
            with patch('config.MATRIX_HOMESERVER', 'https://matrix.org'):
                with patch('config.MATRIX_USER', '@user:matrix.org'):
                    bot = MatrixBot(self.bridge)
                    bot.client = mock_instance
                    bot.room_id = '!room:matrix.org'
                    
                    event_id = await bot.send_message("Reply text", reply_to="$original")
                    
                    self.assertEqual(event_id, "$event456")
                    
                    # Verify reply structure in content
                    call_args = mock_instance.room_send.call_args
                    content = call_args[1]['content']
                    self.assertIn('m.relates_to', content)
                    self.assertEqual(content['m.relates_to']['m.in_reply_to']['event_id'], "$original")
        
        asyncio.run(run())

    @patch('matrix_bot.AsyncClient')
    def test_edit_message(self, mock_client):
        async def run():
            mock_instance = AsyncMock()
            mock_client.return_value = mock_instance
            
            with patch('config.MATRIX_HOMESERVER', 'https://matrix.org'):
                with patch('config.MATRIX_USER', '@user:matrix.org'):
                    bot = MatrixBot(self.bridge)
                    bot.client = mock_instance
                    bot.room_id = '!room:matrix.org'
                    
                    await bot.edit_message("$event789", "Edited text", "<i>Edited text</i>")
                    
                    # Verify edit structure
                    call_args = mock_instance.room_send.call_args
                    content = call_args[1]['content']
                    self.assertEqual(content['m.new_content']['body'], "Edited text")
                    self.assertEqual(content['m.relates_to']['rel_type'], "m.replace")
                    self.assertEqual(content['m.relates_to']['event_id'], "$event789")
        
        asyncio.run(run())

    @patch('matrix_bot.AsyncClient')
    def test_get_display_name_room_specific(self, mock_client):
        async def run():
            mock_instance = AsyncMock()
            mock_client.return_value = mock_instance
            
            # Mock get_displayname returning room-specific name
            mock_instance.get_displayname.return_value = MagicMock(displayname="RoomName")
            
            with patch('config.MATRIX_HOMESERVER', 'https://matrix.org'):
                with patch('config.MATRIX_USER', '@user:matrix.org'):
                    bot = MatrixBot(self.bridge)
                    bot.client = mock_instance
                    bot.room_id = '!room:matrix.org'
                    
                    name = await bot.get_display_name("@user:matrix.org")
                    
                    self.assertEqual(name, "RoomName")
        
        asyncio.run(run())

    @patch('matrix_bot.AsyncClient')
    def test_get_display_name_fallback(self, mock_client):
        async def run():
            mock_instance = AsyncMock()
            mock_client.return_value = mock_instance
            
            # Mock get_displayname returning None/empty
            mock_instance.get_displayname.return_value = MagicMock(displayname=None)
            
            with patch('config.MATRIX_HOMESERVER', 'https://matrix.org'):
                with patch('config.MATRIX_USER', '@user:matrix.org'):
                    bot = MatrixBot(self.bridge)
                    bot.client = mock_instance
                    bot.room_id = '!room:matrix.org'
                    
                    name = await bot.get_display_name("@user:matrix.org")
                    
                    # Should return user ID as fallback
                    self.assertEqual(name, "@user:matrix.org")
        
        asyncio.run(run())

    @patch('matrix_bot.AsyncClient')
    def test_on_room_message_filters_own_messages(self, mock_client):
        async def run():
            mock_instance = AsyncMock()
            mock_client.return_value = mock_instance
            
            with patch('config.MATRIX_HOMESERVER', 'https://matrix.org'):
                with patch('config.MATRIX_USER', '@bot:matrix.org'):
                    bot = MatrixBot(self.bridge)
                    bot.client = mock_instance
                    bot.room_id = '!room:matrix.org'
                    
                    # Create mock event from bot itself
                    room = MagicMock(spec=MatrixRoom)
                    room.room_id = '!room:matrix.org'
                    
                    event = MagicMock(spec=RoomMessageText)
                    event.sender = '@bot:matrix.org'
                    event.body = "Message from bot"
                    
                    await bot._on_room_message(room, event)
                    
                    # Should NOT call handle_matrix_message for own messages
                    self.bridge.handle_matrix_message.assert_not_called()
        
        asyncio.run(run())

    @patch('matrix_bot.AsyncClient')
    def test_on_room_message_filters_wrong_room(self, mock_client):
        async def run():
            mock_instance = AsyncMock()
            mock_client.return_value = mock_instance
            
            with patch('config.MATRIX_HOMESERVER', 'https://matrix.org'):
                with patch('config.MATRIX_USER', '@bot:matrix.org'):
                    bot = MatrixBot(self.bridge)
                    bot.client = mock_instance
                    bot.room_id = '!correct:matrix.org'
                    
                    # Create mock event from different room
                    room = MagicMock(spec=MatrixRoom)
                    room.room_id = '!wrong:matrix.org'
                    
                    event = MagicMock(spec=RoomMessageText)
                    event.sender = '@user:matrix.org'
                    event.body = "Message"
                    
                    await bot._on_room_message(room, event)
                    
                    # Should NOT call handle_matrix_message for wrong room
                    self.bridge.handle_matrix_message.assert_not_called()
        
        asyncio.run(run())

    @patch('matrix_bot.AsyncClient')
    def test_on_room_message_processes_valid(self, mock_client):
        async def run():
            mock_instance = AsyncMock()
            mock_client.return_value = mock_instance
            
            with patch('config.MATRIX_HOMESERVER', 'https://matrix.org'):
                with patch('config.MATRIX_USER', '@bot:matrix.org'):
                    bot = MatrixBot(self.bridge)
                    bot.client = mock_instance
                    bot.room_id = '!room:matrix.org'
                    
                    # Create valid event
                    room = MagicMock(spec=MatrixRoom)
                    room.room_id = '!room:matrix.org'
                    
                    event = MagicMock(spec=RoomMessageText)
                    event.sender = '@user:matrix.org'
                    event.body = "Hello from user"
                    
                    await bot._on_room_message(room, event)
                    
                    # Should call handle_matrix_message
                    self.bridge.handle_matrix_message.assert_called_once_with(event)
        
        asyncio.run(run())

    @patch('matrix_bot.AsyncClient')
    def test_on_reaction(self, mock_client):
        async def run():
            mock_instance = AsyncMock()
            mock_client.return_value = mock_instance
            
            with patch('config.MATRIX_HOMESERVER', 'https://matrix.org'):
                with patch('config.MATRIX_USER', '@bot:matrix.org'):
                    bot = MatrixBot(self.bridge)
                    bot.client = mock_instance
                    bot.room_id = '!room:matrix.org'
                    
                    # Create reaction event
                    room = MagicMock(spec=MatrixRoom)
                    room.room_id = '!room:matrix.org'
                    
                    event = MagicMock(spec=ReactionEvent)
                    event.sender = '@user:matrix.org'
                    
                    await bot._on_reaction(room, event)
                    
                    # Should call handle_matrix_reaction
                    self.bridge.handle_matrix_reaction.assert_called_once_with(event)
        
        asyncio.run(run())

    @patch('matrix_bot.AsyncClient')
    def test_stop(self, mock_client):
        async def run():
            mock_instance = AsyncMock()
            mock_client.return_value = mock_instance
            
            with patch('config.MATRIX_HOMESERVER', 'https://matrix.org'):
                with patch('config.MATRIX_USER', '@user:matrix.org'):
                    bot = MatrixBot(self.bridge)
                    bot.client = mock_instance
                    bot.running = True
                    
                    await bot.stop()
                    
                    self.assertFalse(bot.running)
                    mock_instance.close.assert_called_once()
        
        asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
