import asyncio
import sys
import os

# Railway ejecuta desde /app — aseguramos path correcto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.makedirs("logs", exist_ok=True)

from src.bot_multicoin import main

if __name__ == "__main__":
    asyncio.run(main())
