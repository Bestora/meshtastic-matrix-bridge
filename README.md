# Meshtastic <-> Matrix Bridge with MQTT Support

A Python bridge to connect a Meshtastic mesh (via MQTT and/or Local node) to a Matrix room.

## Features

- **Bidirectional Communication**:
    - **Mesh -> Matrix**: Forwards messages from the mesh to a Matrix room.
    - **Matrix -> Mesh**: Forwards messages from Matrix users to the mesh.
- **Message Aggregation**:
    - Updates Matrix messages with reception stats (RSSI/SNR) and gateway info as multiple nodes report the same packet.
    - Handles deduplication if a packet is received via both MQTT and direct.
- **Reaction Sync**:
    - **Mesh -> Matrix**: Tapbacks in the mesh update the original Matrix message with the emoji and sender.
    - **Matrix -> Mesh**: Reactions in Matrix are sent as Tapbacks to the mesh.
- **Message Handling**:
    - **Long Messages**: Automatically splits Matrix messages > 200 chars into multiple packets.
    - **Usernames**: Prepends `[Username]:` to Matrix messages sent to the mesh.
- **Encryption Support**:
    - Supports connecting to TLS-enabled MQTT brokers.
    - Supports decrypting AES-encrypted Meshtastic packets (using `meshtastic` library).

## Requirements

- Python 3.9+
- A Meshtastic Node connected via TCP/IP (WiFi) or Serial (though config focuses on TCP).
- Access to an MQTT broker (optional, but recommended for mesh-wide visibility).
- A Matrix Bot account.

## Setup

1.  Clone the repository.
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
3.  Copy `.env.example` to `.env` and configure it:
    ```bash
    cp .env.example .env
    ```
4.  Run the bridge:
    ```bash
    python main.py
    ```

## Configuration

See `.env.example` for all available options.

## Architecture

The bridge uses `asyncio` to manage concurrent connections:
- **MatrixBot**: Uses `matrix-nio` to listen for room events.
- **MqttClient**: Uses `paho-mqtt` to subscribe to the mesh topic `msh/EU_868/...`.
- **MeshtasticInterface**: Uses the official `meshtastic` python library to connect to the local node.

A central state manager tracks `Packet ID` <-> `Matrix Event ID` mappings to handle edits and reactions.
