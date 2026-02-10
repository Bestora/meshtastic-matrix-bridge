#!/usr/bin/env python3
"""
Entry point for the Meshtastic-Matrix Bridge.
This script should be run from the project root directory.
"""
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import and run the main function
from src.main import main
import asyncio

if __name__ == "__main__":
    from src import config
    config.validate_config()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")
