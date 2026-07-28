#!/usr/bin/env python3
"""Repository entry point for the ComfyUI model downloader.

The implementation lives with the ComfyUI deployment scripts so the same file
can be copied to /app/pj_comfyui and run with its sibling virtual environment.
"""

from __future__ import annotations

import runpy
from pathlib import Path


IMPLEMENTATION = Path(__file__).resolve().parents[1] / "pj_compyui" / "download_comfyui_model.py"
runpy.run_path(str(IMPLEMENTATION), run_name="__main__")
