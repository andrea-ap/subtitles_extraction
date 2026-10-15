#!/usr/bin/env python3
"""Versione da riga di comando (usa lo stesso motore di app.py).

    runtime\python\python.exe mkv2sub_it.py film.mkv [--model small|medium|large-v3] [--lang auto|en|es|ru|uk] [--force]
"""
import subprocess
import sys
from pathlib import Path

app = Path(__file__).with_name("app.py")
sys.exit(subprocess.call([sys.executable, str(app), "--cli", *sys.argv[1:]]))
