import asyncio
import logging
import signal
import sys
from bridge import MeshtasticMatrixBridge
import config

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    bridge = MeshtasticMatrixBridge()
    
    # Handle shutdown signals
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    
    def signal_handler():
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await bridge.start()
        # Keep running until signal
        await stop_event.wait()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        await bridge.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
