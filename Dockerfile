FROM python:3.11-slim

# Directorio de trabajo
WORKDIR /app

# Dependencias primero (cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código fuente
COPY . .

# Railway inyecta variables de entorno automáticamente
# No hace falta EXPOSE (no es servidor web)

CMD ["python", "main.py"]
