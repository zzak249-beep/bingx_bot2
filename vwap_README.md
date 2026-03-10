# 🚀 BingX VWAP+EMA9 Bot v1.1

[cite_start]Bot de alta probabilidad optimizado para temporalidades de 15m. 

### 🛠️ Instalación Rápida
1. Clona este repositorio.
2. Crea un entorno virtual: `python -m venv venv`.
3. Instala dependencias: `pip install -r requirements.txt`.
4. Configura tus llaves en el archivo `.env`.
5. Ejecuta: `python vwap_bot.py`.

### 📈 Estrategia
- [cite_start]**Entrada:** Precio toca banda 2σ de VWAP con confirmación de dirección en EMA 9. 
- [cite_start]**Salida:** TP parcial (50%) en 2×ATR, Trailing Stop activo y cierre total en 4×ATR.
