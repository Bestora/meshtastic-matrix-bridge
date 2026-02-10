import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MATRIX_HOMESERVER = os.getenv("MATRIX_HOMESERVER")
MATRIX_USER = os.getenv("MATRIX_USER")
MATRIX_PASSWORD = os.getenv("MATRIX_PASSWORD")
MATRIX_ROOM_ID = os.getenv("MATRIX_ROOM_ID")

MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
MQTT_TOPIC = os.getenv("MQTT_TOPIC")
MQTT_USE_TLS = os.getenv("MQTT_USE_TLS", "false").lower() == "true"

MESHTASTIC_HOST = os.getenv("MESHTASTIC_HOST")
MESHTASTIC_PORT = int(os.getenv("MESHTASTIC_PORT", 4403))
MESHTASTIC_CHANNEL_IDX = int(os.getenv("MESHTASTIC_CHANNEL_IDX", 0))
MESHTASTIC_CHANNEL_PSK = os.getenv("MESHTASTIC_CHANNEL_PSK")
MESHTASTIC_CHANNELS = [x.strip() for x in os.getenv("MESHTASTIC_CHANNELS", "0").split(",") if x.strip()]

NODE_DB_PATH = os.getenv("NODE_DB_PATH", "/data/nodes.db")


def validate_config():
    required_configs = {
        "MATRIX_HOMESERVER": MATRIX_HOMESERVER,
        "MATRIX_USER": MATRIX_USER,
        "MATRIX_PASSWORD": MATRIX_PASSWORD,
        "MATRIX_ROOM_ID": MATRIX_ROOM_ID,
    }
    
    optional_configs = {
        "MQTT_BROKER": MQTT_BROKER,
        "MESHTASTIC_HOST": MESHTASTIC_HOST,
    }
    
    missing_required = [k for k, v in required_configs.items() if not v]
    if missing_required:
        logger.error(f"Missing required configuration: {', '.join(missing_required)}")
        sys.exit(1)
    
    if not MQTT_BROKER and not MESHTASTIC_HOST:
        logger.error("Either MQTT_BROKER or MESHTASTIC_HOST must be configured")
        sys.exit(1)
    
    logger.info("Configuration validated successfully")
