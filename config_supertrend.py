"""
config_supertrend.py - Configuracion y presets
"""

PRESETS = {
    'conservative': {
        'st_period':      12,
        'st_mult':        3.5,
        'rsi_period':     14,
        'rsi_ob':         70,
        'rsi_os':         30,
        'min_confidence': 85,
        'sl_mult':        1.2,
        'tp_mult':        2.0,
    },
    'balanced': {
        'st_period':      10,
        'st_mult':        3.0,
        'rsi_period':     14,
        'rsi_ob':         65,
        'rsi_os':         35,
        'min_confidence': 75,
        'sl_mult':        1.5,
        'tp_mult':        2.5,
    },
    'aggressive': {
        'st_period':      7,
        'st_mult':        2.5,
        'rsi_period':     10,
        'rsi_ob':         60,
        'rsi_os':         40,
        'min_confidence': 65,
        'sl_mult':        2.0,
        'tp_mult':        3.0,
    },
}


def get_config(preset: str = 'balanced') -> dict:
    if preset not in PRESETS:
        raise ValueError(f"Preset '{preset}' no valido. Usa: {list(PRESETS.keys())}")
    return PRESETS[preset]
