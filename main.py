"""
Entry point — starts the QF×JP bot
"""
import asyncio
import os
from src.bot import main

os.makedirs("logs", exist_ok=True)

if __name__ == "__main__":
    asyncio.run(main())
