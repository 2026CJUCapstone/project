#!/usr/bin/env python3
"""CLI compatibility wrapper for the shared static/managed proxy renderer."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.api_proxy_config import main, render


if __name__ == '__main__':
    main()
