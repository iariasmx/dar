"""Utilidades compartidas para conexiones a MySQL."""

import mysql.connector
from sqlalchemy import create_engine

from .config import db_config


def crear_url_mysql():
    return (
        f"mysql+mysqlconnector://{db_config['user']}:{db_config['password']}"
        f"@{db_config['host']}:{db_config.get('port', 3306)}/{db_config['database']}"
    )


def crear_engine_mysql():
    return create_engine(crear_url_mysql())


def conectar_mysql():
    return mysql.connector.connect(**db_config)
