FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir ccxt pandas numpy requests

COPY saty_v19.py /app/bot.py

CMD ["python", "bot.py"]
