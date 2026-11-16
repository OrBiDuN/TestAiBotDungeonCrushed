"""Persistent files live beside the EXE; bundled assets live inside the bundle."""
import sys
from pathlib import Path

RESOURCE_DIR = Path(__file__).resolve().parent
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else RESOURCE_DIR
