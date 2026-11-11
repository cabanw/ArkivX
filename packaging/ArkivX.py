"""Punto de entrada para PyInstaller (fuera del paquete, para que
`from arkivx import core` funcione igual que con `python -m arkivx.app`)."""
import sys

from arkivx.app import main

sys.exit(main())
