"""Configuración compartida de MySQL desde el entorno y el archivo .env."""

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)


def cargar_config_db():
    """Valida la conexión sin abrirla; el entorno tiene prioridad sobre .env."""
    campos = {
        'host': 'DB_HOST',
        'user': 'DB_USER',
        'password': 'DB_PASSWORD',
        'database': 'DB_NAME',
    }
    faltantes = [variable for variable in campos.values() if not os.getenv(variable)]
    if faltantes:
        raise ValueError(
            'Faltan variables de conexión: ' + ', '.join(faltantes)
            + '. Configura .env tomando .env.example como referencia.'
        )

    try:
        puerto = int(os.getenv('DB_PORT', '3306'))
    except ValueError:
        raise ValueError('DB_PORT debe ser un entero entre 1 y 65535.') from None
    if not 1 <= puerto <= 65535:
        raise ValueError('DB_PORT debe ser un entero entre 1 y 65535.')

    return {**{campo: os.environ[variable] for campo, variable in campos.items()}, 'port': puerto}


db_config = cargar_config_db()
