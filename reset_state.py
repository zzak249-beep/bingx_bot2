#!/usr/bin/env python3
"""
reset_state.py — Borra el estado guardado del circuit breaker
Ejecutar UNA VEZ después de subir el nuevo risk_manager.py
Railway > Logs > puedes añadir al inicio de main.py o ejecutar manualmente
"""
import os, json
from datetime import date

files = ["risk_state.json", "positions.json"]
for f in files:
    if os.path.exists(f):
        os.remove(f)
        print(f"✅ Borrado: {f}")
    else:
        print(f"   No existe: {f}")

print("\n✅ Estado reseteado — el bot arrancará limpio")
