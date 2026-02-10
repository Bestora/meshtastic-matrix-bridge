# Project Structure

## Overview

The Meshtastic-Matrix Bridge has been organized following Python best practices for a clean, maintainable project structure.

## Directory Layout

```
meshtastic-matrix-bridge/
├── src/                           # Main application code
│   ├── __init__.py               # Package marker
│   ├── main.py                   # Application entry point
│   ├── bridge.py                 # Core bridge orchestration logic
│   ├── config.py                 # Configuration management with validation
│   ├── constants.py              # Application-wide constants
│   ├── models.py                 # Data models (MessageState, ReceptionStats)
│   ├── utils.py                  # Utility functions (formatting, parsing)
│   │
│   ├── adapters/                 # External service adapters
│   │   ├── __init__.py          # Package marker
│   │   ├── matrix_bot.py        # Matrix client (matrix-nio)
│   │   ├── mqtt_client.py       # MQTT client (paho-mqtt)
│   │   └── meshtastic_interface.py # Meshtastic node interface
│   │
│   └── database/                 # Database layer
│       ├── __init__.py          # Package marker
│       └── node_database.py     # SQLite persistence
│
├── tests/                        # Test suite
│   ├── __init__.py              # Package marker
│   ├── run_all_tests.py         # Test runner with reporting
│   ├── test_bridge.py           # Core bridge tests
│   ├── test_bridge_advanced.py  # Advanced bridge features tests
│   ├── test_coverage_extended.py # Extended coverage tests
│   ├── test_database.py         # Database tests
│   ├── test_matrix_bot.py       # Matrix bot tests
│   ├── test_meshtastic_interface.py # Meshtastic interface tests
│   └── test_mqtt_client.py      # MQTT client tests
│
├── docs/                         # Documentation
│   ├── OPTIMIZATIONS_AND_BUGFIXES.md # Bug fixes and optimizations
│   ├── REFACTORING.md           # Refactoring history
│   ├── TEST_COVERAGE_FINAL.md   # Complete test coverage report
│   ├── TEST_COVERAGE_ANALYSIS.md # Detailed test analysis
│   ├── TEST_SUMMARY.md          # Feature testing summary
│   ├── UPDATES.md               # Change log
│   └── PROJECT_STRUCTURE.md     # This file
│
├── run.py                        # Main entry point script
├── requirements.txt              # Python dependencies
├── Dockerfile                    # Docker container definition
├── compose.yaml                  # Docker Compose configuration
├── .env.example                  # Environment variables template
├── .gitignore                    # Git ignore rules
└── README.md                     # Project readme

```

## Component Descriptions

### Core Application (`src/`)

#### `main.py`
- Application entry point
- Sets up logging
- Handles shutdown signals (SIGINT, SIGTERM)
- Starts and stops the bridge

#### `bridge.py`
- Central orchestrator and state manager
- Manages packet ID ↔ Matrix event ID mappings
- Coordinates between Matrix, MQTT, and Meshtastic adapters
- Handles message deduplication and aggregation
- Manages reply threading and reactions
- Implements periodic memory cleanup

#### `config.py`
- Loads environment variables from `.env`
- Validates required configuration
- Exports configuration constants
- Provides `validate_config()` function

#### `constants.py`
- Centralized application constants
- Protocol port numbers (TEXT_MESSAGE_APP, NODEINFO_APP, REACTION_APP)
- Size limits (MAX_MESSAGE_LENGTH)
- Default values

#### `models.py`
- Data classes using `@dataclass`
- `MessageState`: Tracks message lifecycle
- `ReceptionStats`: Stores reception metadata (RSSI, SNR, hop count)

#### `utils.py`
- Common utility functions
- `format_stats()`: Format reception statistics
- `node_id_to_str()`: Convert node IDs to hex strings
- `extract_channel_name_from_topic()`: Parse MQTT topics
- `is_emoji_only()`: Detect emoji-only messages

### Adapters (`src/adapters/`)

External service interfaces following the adapter pattern.

#### `matrix_bot.py`
- Matrix client using `matrix-nio`
- Handles Matrix room events
- Sends/edits messages
- Manages display name resolution
- Forwards reactions

#### `mqtt_client.py`
- MQTT client using `paho-mqtt` (v2 API)
- Subscribes to Meshtastic MQTT topics
- Decodes protobuf messages
- Supports AES decryption
- Extracts reception statistics

#### `meshtastic_interface.py`
- Direct connection to local Meshtastic node
- Uses TCP interface
- Imports node database on startup
- Sends text messages and tapbacks
- Handles NODEINFO packets

### Database (`src/database/`)

#### `node_database.py`
- SQLite-backed persistence
- Node name resolution (short/long names)
- Message state persistence
- Safe database operations with context managers
- Migration support

### Tests (`tests/`)

Comprehensive test suite with ~55% coverage.

- **Unit tests**: Individual component testing
- **Integration tests**: Cross-component interactions
- **Feature tests**: End-to-end scenarios
- **Coverage tracking**: Detailed reports in `docs/`

### Documentation (`docs/`)

All project documentation organized by topic:

- **OPTIMIZATIONS_AND_BUGFIXES.md**: Performance improvements and bug fixes
- **REFACTORING.md**: Code refactoring history
- **TEST_COVERAGE_*.md**: Testing documentation
- **PROJECT_STRUCTURE.md**: This file

## Running the Application

### From Source

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bridge
python run.py
```

### With Docker

```bash
# Build and run
docker-compose up -d
```

### Running Tests

```bash
# All tests
python tests/run_all_tests.py

# Individual test files
python -m pytest tests/test_bridge.py
```

## Import Structure

All imports use absolute imports from the `src` package:

```python
# Good
from src.bridge import MeshtasticMatrixBridge
from src.adapters.matrix_bot import MatrixBot
from src.database.node_database import NodeDatabase
from src import config

# Not used
from bridge import MeshtasticMatrixBridge  # Old style
```

## Benefits of This Structure

### 1. **Clarity**
- Clear separation of concerns
- Easy to locate specific functionality
- Logical grouping of related files

### 2. **Maintainability**
- Modular design facilitates changes
- Easy to add new adapters or features
- Clear dependency relationships

### 3. **Scalability**
- Room to grow without clutter
- Easy to add new modules
- Clear extension points

### 4. **Professional**
- Follows Python packaging best practices
- Standard structure recognized by IDEs
- Ready for distribution

### 5. **Testing**
- Clear test organization
- Easy to run specific test suites
- Separate from production code

### 6. **Documentation**
- Centralized documentation
- Easy to find and update docs
- Doesn't clutter root directory

## Migration Notes

### Previous Structure
```
project/
├── main.py
├── bridge.py
├── matrix_bot.py
├── mqtt_client.py
├── meshtastic_interface.py
├── node_database.py
├── test_*.py
├── REFACTORING.md
└── ...
```

### Changes Made
1. ✅ Created `src/`, `tests/`, `docs/` directories
2. ✅ Moved all source files to `src/`
3. ✅ Organized adapters in `src/adapters/`
4. ✅ Moved database to `src/database/`
5. ✅ Moved all tests to `tests/`
6. ✅ Moved all documentation to `docs/`
7. ✅ Updated all imports to use `src.` prefix
8. ✅ Created `run.py` entry point
9. ✅ Updated Dockerfile
10. ✅ Updated README.md

### Backwards Compatibility

⚠️ **Breaking Change**: This restructure changes import paths.

- Old: `from bridge import MeshtasticMatrixBridge`
- New: `from src.bridge import MeshtasticMatrixBridge`

**Migration for external users**: Update your imports to use the `src.` prefix.

## Future Enhancements

Potential future structural improvements:

1. **CLI Module**: `src/cli/` for command-line interface
2. **Logging Module**: `src/logging/` for custom logging configuration
3. **Metrics Module**: `src/metrics/` for Prometheus-style metrics
4. **API Module**: `src/api/` for REST/webhook endpoints
5. **Scripts Directory**: `scripts/` for utility scripts (migrations, setup, etc.)

## Contributing

When adding new files:

1. **Source code** → `src/` or appropriate subdirectory
2. **Tests** → `tests/` with `test_` prefix
3. **Documentation** → `docs/`
4. **Scripts** → Root or `scripts/` directory
5. **Config files** → Root directory

Always use absolute imports from `src` and add appropriate `__init__.py` files for new packages.
