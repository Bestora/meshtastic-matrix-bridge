# Meshtastic <-> Matrix Bridge with MQTT Support

A Python bridge to connect a Meshtastic mesh (via MQTT and/or Local node) to a Matrix room.

## Features

- **Bidirectional Communication**:
    - **Mesh -> Matrix**: Forwards messages from the mesh to a Matrix room.
    - **Matrix -> Mesh**: Forwards messages from Matrix users to the mesh.
- **Message Aggregation**:
    - Updates Matrix messages with reception stats as multiple nodes report the same packet.
    - Shows RSSI/SNR for direct reception (0 hops), or hop count for multi-hop messages.
    - Handles deduplication if a packet is received via both MQTT and direct.
- **Node Name Resolution**:
    - Automatically resolves node IDs (like `!ae614908`) to human-readable names.
    - Listens to NODEINFO packets and maintains a persistent SQLite database.
    - Shows node short names or long names instead of hex IDs.
- **Reply Threading**:
    - Messages sent as replies in Meshtastic appear as notes under the original message in Matrix.
    - Keeps conversation context clear and organized.
- **Reaction Sync**:
    - **Mesh -> Matrix**: Tapbacks in the mesh update the original Matrix message with the emoji and sender.
    - **Matrix -> Mesh**: Reactions in Matrix are sent as Tapbacks to the mesh.
- **Channel Filtering**:
    - **Configurable Channels**: Only messages from specific channels (e.g., "LongFast") are bridged to Matrix.
    - **Default Index**: Defaults to channel 0, but can be configured as a comma-separated list.
- **Message Handling**:
    - **Long Messages**: Automatically splits Matrix messages > 200 chars into multiple packets.
    - **Display Names**: Uses Matrix display names instead of full user IDs in forwarded messages.
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
- **MatrixBot** (`matrix_bot.py`): Uses `matrix-nio` to listen for room events.
- **MqttClient** (`mqtt_client.py`): Uses `paho-mqtt` to subscribe to the mesh topic `msh/EU_868/...`.
- **MeshtasticInterface** (`meshtastic_interface.py`): Uses the official `meshtastic` python library to connect to the local node.
- **MeshtasticMatrixBridge** (`bridge.py`): Central state manager that tracks `Packet ID` <-> `Matrix Event ID` mappings to handle edits and reactions.
- **NodeDatabase** (`node_database.py`): SQLite-backed persistence for node names and message states.
- **Utils** (`utils.py`): Common utility functions for formatting and text processing.
- **Constants** (`constants.py`): Centralized constants and magic numbers.

## Code Quality

This project has been recently refactored to improve:
- Code organization and modularity
- Reduction of code duplication
- Type safety with type hints
- Better configuration validation
- Modern API usage (MQTT v2)

See `REFACTORING.md` for details on improvements made.

## Testing

Run tests with:
```bash
# Run all tests with comprehensive report
python run_all_tests.py

# Or run individual test suites
python test_bridge.py                  # Core tests (6/6 passing)
python test_coverage_extended.py       # Extended tests (22/22 passing)  
python test_database.py                # Database tests (7/13 passing)
python test_matrix_bot.py              # Matrix bot tests (9/12 passing)
python test_meshtastic_interface.py    # Meshtastic tests (9/11 passing)
python test_mqtt_client.py             # MQTT tests (7/8 passing)
python test_bridge_advanced.py         # Advanced tests (14/33 passing)
```

**Test Coverage**: ~55% estimated line coverage
- **105 tests total**: 74 passing (70.5%), 6 failing, 25 errors
- **7 test files**: 2 fully passing, 5 partially passing
- See `TEST_COVERAGE_FINAL.md` for complete test report
- See `TEST_SUMMARY.md` for feature analysis
- See `TEST_COVERAGE_ANALYSIS.md` for detailed breakdown

## Warning
This project was initially AI-generated, so while it has been refactored and tested, use with caution in production environments.