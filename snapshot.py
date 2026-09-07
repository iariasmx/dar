import mysql.connector

from config import db_config

conexion = None
cursor = None

try:
    conexion = mysql.connector.connect(**db_config)
    cursor = conexion.cursor()

    # 1. Leer el estado actual de las interfaces activas
    query_origen = """
                   SELECT ID_INTERFACE, ID_EQUIPO, SLOT, ANCHO_BANDA, TRAFICO_95
                   FROM EQUIPOS_DSL_INTERFACE_L1
                   WHERE STATUS = 'UP' \
                      OR SHUTDOWN = 0; \
                   """
    cursor.execute(query_origen)
    interfaces_actuales = cursor.fetchall()

    # 2. Insertar los datos en la tabla histórica con la fecha de hoy
    query_destino = """
                    INSERT INTO HISTORICO_DSL_INTERFACE
                        (ID_INTERFACE, ID_EQUIPO, SLOT, ANCHO_BANDA, TRAFICO_95)
                    VALUES (%s, %s, %s, %s, %s); \
                    """

    cursor.executemany(query_destino, interfaces_actuales)
    conexion.commit()

    print(f"✅ Snapshot exitoso. Se respaldaron {cursor.rowcount} interfaces para el historial de hoy.")

except mysql.connector.Error as err:
    print(f"❌ Error en el proceso: {err}")
finally:
    if cursor is not None:
        cursor.close()
    if conexion is not None and conexion.is_connected():
        conexion.close()
