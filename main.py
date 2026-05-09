import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from src.bot import main

if __name__ == "__main__":
    asyncio.run(main())
