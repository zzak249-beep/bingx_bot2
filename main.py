#!/usr/bin/env python3
"""
Bot de Trading Automatizado - BingX
Combina Linear Regression Channel + Liquidity Levels (PDH/PDL)
"""

import os
import time
import logging
from datetime import datetime
from typing import Optional
import asyncio
from dotenv import load_dotenv

from strategy import TradingStrategy
from bingx_client import BingXClient
from telegram_notifier import TelegramNotifier

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()


class TradingBot:
    """Bot principal de trading multi-par"""
    
    def __init__(self):
        """Inicializar el bot"""
        # Configuración de pares múltiples
        symbols_str = os.getenv('SYMBOLS', 'BTC-USDT,ETH-USDT,SOL-USDT')
        self.symbols = [s.strip() for s in symbols_str.split(',')]
        
        self.timeframe = os.getenv('TIMEFRAME', '15m')
        self.check_interval = int(os.getenv('CHECK_INTERVAL', '60'))
        self.max_position_size = float(os.getenv('MAX_POSITION_SIZE', '100'))
        self.max_positions = int(os.getenv('MAX_POSITIONS', '3'))
        
        # Inicializar componentes
        self.exchange = BingXClient()
        self.strategy = TradingStrategy()
        self.telegram = TelegramNotifier()
        
        # Rastreo de posiciones por símbolo
        self.active_positions = {}
        self.last_analysis = {}
        
        logger.info(f"🤖 Bot inicializado - Pares: {len(self.symbols)}, Timeframe: {self.timeframe}")
        
        symbols_list = '\n'.join([f"  • {s}" for s in self.symbols])
        self.telegram.send_message(
            f"🤖 Bot Multi-Par Iniciado\n\n"
            f"📊 Analizando {len(self.symbols)} pares:\n{symbols_list}\n\n"
            f"⏱ Timeframe: {self.timeframe}\n"
            f"💰 Max posiciones: {self.max_positions}\n"
            f"📦 Tamaño por posición: ${self.max_position_size}"
        )
    
    async def run(self):
        """Loop principal del bot"""
        logger.info("🚀 Iniciando loop de trading...")
        
        while True:
            try:
                await self.trading_cycle()
                await asyncio.sleep(self.check_interval)
                
            except KeyboardInterrupt:
                logger.info("⏹ Bot detenido por el usuario")
                self.telegram.send_message("⏹ Bot detenido manualmente")
                break
                
            except Exception as e:
                logger.error(f"❌ Error en el ciclo de trading: {e}", exc_info=True)
                self.telegram.send_message(f"⚠️ Error: {str(e)}")
                await asyncio.sleep(60)
    
    async def trading_cycle(self):
        """Ciclo de trading: analizar todos los pares y ejecutar operaciones"""
        
        # Analizar todos los pares en paralelo
        tasks = [self.analyze_symbol(symbol) for symbol in self.symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Procesar resultados
        signals = []
        for symbol, result in zip(self.symbols, results):
            if isinstance(result, Exception):
                logger.error(f"Error analizando {symbol}: {result}")
                continue
            if result and result['action'] != 'NONE':
                signals.append((symbol, result))
        
        # Ordenar señales por fuerza (proximidad a niveles clave)
        signals.sort(key=lambda x: self._calculate_signal_strength(x[1]), reverse=True)
        
        # Ejecutar las mejores señales (respetando límite de posiciones)
        for symbol, signal in signals:
            if len(self.active_positions) >= self.max_positions:
                logger.info(f"⏸️ Límite de posiciones alcanzado ({self.max_positions})")
                break
            
            await self.process_signal(symbol, signal)
    
    async def analyze_symbol(self, symbol: str) -> dict:
        """Analizar un símbolo específico"""
        try:
            # 1. Obtener datos del mercado
            candles = await self.exchange.get_klines(symbol, self.timeframe, limit=150)
            if not candles:
                return {'action': 'NONE'}
            
            # 2. Analizar estrategia
            signal = self.strategy.analyze(candles)
            signal['symbol'] = symbol
            
            # 3. Guardar último análisis
            self.last_analysis[symbol] = {
                'timestamp': datetime.now(),
                'signal': signal
            }
            
            return signal
            
        except Exception as e:
            logger.error(f"Error analizando {symbol}: {e}")
            return {'action': 'NONE'}
    
    async def process_signal(self, symbol: str, signal: dict):
        """Procesar señal de un símbolo"""
        
        # Verificar posición actual
        current_position = await self.exchange.get_position(symbol)
        
        # Ejecutar según la señal
        if signal['action'] == 'LONG' and not current_position and symbol not in self.active_positions:
            await self.open_long(symbol, signal)
            
        elif signal['action'] == 'SHORT' and not current_position and symbol not in self.active_positions:
            await self.open_short(symbol, signal)
            
        elif signal['action'] == 'CLOSE_LONG' and current_position and current_position['side'] == 'LONG':
            await self.close_position(symbol, current_position, "Señal de cierre")
            
        elif signal['action'] == 'CLOSE_SHORT' and current_position and current_position['side'] == 'SHORT':
            await self.close_position(symbol, current_position, "Señal de cierre")
        
        # Gestionar posición abierta
        if current_position:
            await self.manage_position(symbol, current_position, signal)
    
    def _calculate_signal_strength(self, signal: dict) -> float:
        """Calcular fuerza de la señal (mayor = mejor)"""
        if signal['action'] == 'NONE':
            return 0.0
        
        # Calcular ratio riesgo/beneficio
        risk = abs(signal['price'] - signal['stop_loss'])
        reward = abs(signal['take_profit'] - signal['price'])
        
        if risk == 0:
            return 0.0
        
        rr_ratio = reward / risk
        return rr_ratio
    
    async def open_long(self, symbol: str, signal: dict):
        """Abrir posición LONG"""
        try:
            price = signal['price']
            stop_loss = signal['stop_loss']
            take_profit = signal['take_profit']
            
            quantity = self.calculate_position_size(price, stop_loss)
            
            logger.info(f"📈 [{symbol}] Abriendo LONG - Precio: {price}, SL: {stop_loss}, TP: {take_profit}")
            
            order = await self.exchange.place_order(
                symbol=symbol,
                side='BUY',
                quantity=quantity,
                price=price,
                stop_loss=stop_loss,
                take_profit=take_profit
            )
            
            if order:
                # Registrar posición activa
                self.active_positions[symbol] = {
                    'side': 'LONG',
                    'entry_price': price,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'quantity': quantity,
                    'opened_at': datetime.now()
                }
                
                message = (
                    f"✅ LONG ABIERTO - {symbol}\n"
                    f"📊 Precio: {price:.4f}\n"
                    f"🛑 Stop Loss: {stop_loss:.4f}\n"
                    f"🎯 Take Profit: {take_profit:.4f}\n"
                    f"📦 Cantidad: {quantity:.6f}\n"
                    f"📈 {signal['reasons']}\n"
                    f"💼 Posiciones activas: {len(self.active_positions)}/{self.max_positions}"
                )
                self.telegram.send_message(message)
                logger.info(f"✅ [{symbol}] Posición LONG abierta exitosamente")
                
        except Exception as e:
            logger.error(f"❌ [{symbol}] Error abriendo LONG: {e}", exc_info=True)
            self.telegram.send_message(f"❌ Error abriendo LONG en {symbol}: {str(e)}")
    
    async def open_short(self, symbol: str, signal: dict):
        """Abrir posición SHORT"""
        try:
            price = signal['price']
            stop_loss = signal['stop_loss']
            take_profit = signal['take_profit']
            
            quantity = self.calculate_position_size(price, stop_loss)
            
            logger.info(f"📉 [{symbol}] Abriendo SHORT - Precio: {price}, SL: {stop_loss}, TP: {take_profit}")
            
            order = await self.exchange.place_order(
                symbol=symbol,
                side='SELL',
                quantity=quantity,
                price=price,
                stop_loss=stop_loss,
                take_profit=take_profit
            )
            
            if order:
                # Registrar posición activa
                self.active_positions[symbol] = {
                    'side': 'SHORT',
                    'entry_price': price,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'quantity': quantity,
                    'opened_at': datetime.now()
                }
                
                message = (
                    f"✅ SHORT ABIERTO - {symbol}\n"
                    f"📊 Precio: {price:.4f}\n"
                    f"🛑 Stop Loss: {stop_loss:.4f}\n"
                    f"🎯 Take Profit: {take_profit:.4f}\n"
                    f"📦 Cantidad: {quantity:.6f}\n"
                    f"📉 {signal['reasons']}\n"
                    f"💼 Posiciones activas: {len(self.active_positions)}/{self.max_positions}"
                )
                self.telegram.send_message(message)
                logger.info(f"✅ [{symbol}] Posición SHORT abierta exitosamente")
                
        except Exception as e:
            logger.error(f"❌ [{symbol}] Error abriendo SHORT: {e}", exc_info=True)
            self.telegram.send_message(f"❌ Error abriendo SHORT en {symbol}: {str(e)}")
    
    async def close_position(self, symbol: str, position: dict, reason: str):
        """Cerrar posición actual"""
        try:
            logger.info(f"🔄 [{symbol}] Cerrando posición - Razón: {reason}")
            
            result = await self.exchange.close_position(symbol, position['side'])
            
            if result:
                pnl = result.get('pnl', 0)
                pnl_emoji = "💚" if pnl > 0 else "❤️"
                
                # Remover de posiciones activas
                if symbol in self.active_positions:
                    del self.active_positions[symbol]
                
                message = (
                    f"🔒 POSICIÓN CERRADA - {symbol}\n"
                    f"{pnl_emoji} PnL: {pnl:.2f} USDT\n"
                    f"📝 Razón: {reason}\n"
                    f"💼 Posiciones restantes: {len(self.active_positions)}"
                )
                self.telegram.send_message(message)
                logger.info(f"✅ [{symbol}] Posición cerrada - PnL: {pnl}")
                
        except Exception as e:
            logger.error(f"❌ [{symbol}] Error cerrando posición: {e}", exc_info=True)
            self.telegram.send_message(f"❌ Error cerrando posición en {symbol}: {str(e)}")
    
    async def manage_position(self, symbol: str, position: dict, signal: dict):
        """Gestionar posición abierta (trailing stop, etc.)"""
        # Aquí puedes implementar trailing stop o ajustes dinámicos
        pass
    
    def calculate_position_size(self, entry_price: float, stop_loss: float) -> float:
        """Calcular tamaño de posición basado en riesgo (2%)"""
        risk_per_trade = self.max_position_size * 0.02
        price_diff = abs(entry_price - stop_loss)
        
        if price_diff == 0:
            return 0
        
        quantity = risk_per_trade / price_diff
        return round(quantity, 8)


async def main():
    """Función principal"""
    bot = TradingBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
