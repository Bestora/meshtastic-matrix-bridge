import os
from dotenv import load_dotenv

load_dotenv()

# Matrix
MATRIX_HOMESERVER = os.getenv("MATRIX_HOMESERVER")
MATRIX_USER = os.getenv("MATRIX_USER")
MATRIX_PASSWORD = os.getenv("MATRIX_PASSWORD")
MATRIX_ROOM_ID = os.getenv("MATRIX_ROOM_ID")

# MQTT
MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
MQTT_TOPIC = os.getenv("MQTT_TOPIC")
MQTT_USE_TLS = os.getenv("MQTT_USE_TLS", "false").lower() == "true"

# Meshtastic
MESHTASTIC_HOST = os.getenv("MESHTASTIC_HOST")
MESHTASTIC_CHANNEL_IDX = int(os.getenv("MESHTASTIC_CHANNEL_IDX", 0))
MESHTASTIC_CHANNEL_PSK = os.getenv("MESHTASTIC_CHANNEL_PSK")
