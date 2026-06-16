FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all source files
COPY *.py .

# Railway sets PORT env var automatically
ENV PORT=8080

CMD ["python", "main.py"]
