"""Resumen matricial de tarjetas de hardware para el dashboard principal."""

import pandas as pd
import streamlit as st

from .db import conectar_mysql


@st.cache_data
def cargar_datos_hardware_dinamico():
    """Obtiene las tarjetas de equipos activos una única vez por caché."""
    query = """
        SELECT DIVISIONAL, SITIO_UNINET, NOMBRE_EQUIPO,
               MODELO AS MODELO_EQUIPO, SLOT, NUM_PARTE_TARJETA, STATUS_EQUIPO
        FROM SIRU_DSL
        WHERE NOMBRE_EQUIPO IS NOT NULL AND STATUS_EQUIPO != 'BAJA';
    """
    conexion = None
    try:
        conexion = conectar_mysql()
        return pd.read_sql(query, conexion)
    except Exception as error:
        st.error(f"❌ Error al conectar o consultar MySQL: {error}")
        return pd.DataFrame()
    finally:
        if conexion is not None and conexion.is_connected():
            conexion.close()


def _aplicar_filtros(datos, divisional, sitio, modelo, equipo):
    filtros = {
        "DIVISIONAL": divisional,
        "SITIO_UNINET": sitio,
        "MODELO_EQUIPO": modelo,
        "NOMBRE_EQUIPO": equipo,
    }
    resultado = datos.copy()
    for columna, valor in filtros.items():
        if valor and valor != "TODOS":
            resultado = resultado[resultado[columna] == valor]
    return resultado


def _estilo_matriz(datos):
    estilos = pd.DataFrame("", index=datos.index, columns=datos.columns)
    for columna in datos.columns:
        for indice in datos.index:
            if indice == "TOTAL GENERAL" or columna == "TOTAL GENERAL":
                continue
            if pd.notna(datos.loc[indice, columna]) and datos.loc[indice, columna] > 0:
                estilos.loc[indice, columna] = (
                    "background-color: rgba(40, 167, 69, 0.15); color: #1e4620; "
                    "font-weight: bold;"
                )
            else:
                estilos.loc[indice, columna] = "color: #adb5bd; font-size: 0.9em;"
    if "TOTAL GENERAL" in datos.columns:
        estilos["TOTAL GENERAL"] = (
            "font-weight: bold; background-color: rgba(108, 117, 125, 0.12); color: #212529;"
        )
    if "TOTAL GENERAL" in datos.index:
        estilos.loc["TOTAL GENERAL", :] = (
            "font-weight: bold; background-color: rgba(108, 117, 125, 0.12); color: #212529;"
        )
    return estilos


def mostrar_resumen_hardware(divisional="TODOS", sitio="TODOS", modelo="TODOS", equipo="TODOS"):
    """Renderiza la matriz respetando los filtros activos del dashboard."""
    datos = cargar_datos_hardware_dinamico()
    if datos.empty:
        st.warning("⚠️ No se encontraron datos o la conexión a la base de datos falló.")
        return

    datos["NUM_PARTE_TARJETA"] = datos["NUM_PARTE_TARJETA"].fillna("").str.strip()
    datos["SLOT"] = datos["SLOT"].fillna("0")
    tarjetas = datos[datos["NUM_PARTE_TARJETA"] != ""].drop_duplicates(
        subset=["NOMBRE_EQUIPO", "SLOT", "NUM_PARTE_TARJETA"]
    )
    filtrado = _aplicar_filtros(tarjetas, divisional, sitio, modelo, equipo)
    if filtrado.empty:
        st.info("No hay tarjetas para los filtros seleccionados.")
        return

    tabla = pd.crosstab(
        index=filtrado["NOMBRE_EQUIPO"],
        columns=filtrado["NUM_PARTE_TARJETA"],
        margins=True,
        margins_name="TOTAL GENERAL",
    )
    metricas = st.columns(2)
    metricas[0].metric("Equipos Incluidos en Matriz", f"{len(tabla) - 1:,}")
    metricas[1].metric("Suma Total Unidades Físicas", f"{int(tabla.loc['TOTAL GENERAL', 'TOTAL GENERAL']):,}")
    st.markdown("---")
    st.subheader("📊 Distribución Matricial de Inventario")
    st.dataframe(tabla.style.apply(_estilo_matriz, axis=None), width="stretch", hide_index=False)
