import mysql.connector
import pandas as pd
import streamlit as st

from config import db_config


# Reutilizamos la función optimizada con caché para leer los datos de MySQL
@st.cache_data
def cargar_datos_hardware_dinamico():
    query = """
        SELECT 
            DIVISIONAL,
            SITIO_UNINET,
            NOMBRE_EQUIPO,
            MODELO as MODELO_EQUIPO,
            SLOT,
            NUM_PARTE_TARJETA,
            STATUS_EQUIPO
        FROM SIRU_DSL
        WHERE NOMBRE_EQUIPO IS NOT NULL 
          AND STATUS_EQUIPO != 'BAJA';
    """
    try:
        conexion = mysql.connector.connect(**db_config)
        df = pd.read_sql(query, conexion)
        conexion.close()
        return df
    except Exception as e:
        st.error(f"❌ Error al conectar o consultar MySQL: {e}")
        return pd.DataFrame()


# Cargar usando la nueva función limpia de caché
df_siru_resumen = cargar_datos_hardware_dinamico()

if df_siru_resumen.empty:
    st.warning(
        "⚠️ No se encontraron datos o la conexión a la base de datos falló."
    )
    st.stop()

# =====================================================================
# LIMPIEZA Y ELIMINACIÓN DE DUPLICADOS (Evita inflación por subtarjetas)
# =====================================================================
df_siru_resumen["NUM_PARTE_TARJETA"] = (
    df_siru_resumen["NUM_PARTE_TARJETA"].fillna("").str.strip()
)
df_siru_resumen["SLOT"] = df_siru_resumen["SLOT"].fillna("0")

# Filtramos cadenas vacías para analizar solo tarjetas con número de parte real
df_validas = df_siru_resumen[df_siru_resumen["NUM_PARTE_TARJETA"] != ""]

# Nos quedamos únicamente con registros únicos de tarjetas físicas por equipo y slot
df_tarjetas_unicas = df_validas.drop_duplicates(
    subset=["NOMBRE_EQUIPO", "SLOT", "NUM_PARTE_TARJETA"]
)

# =====================================================================
# ⚡ APLICACIÓN DE FILTROS GLOBALES HEREDADOS DE APP.PY
# =====================================================================
df_filtrado = df_tarjetas_unicas.copy()

# El script hereda directamente las variables que seleccionó el usuario en la barra lateral de app.py
if "divisional_seleccionada" in globals() and divisional_seleccionada != "TODOS":
    df_filtrado = df_filtrado[df_filtrado["DIVISIONAL"] == divisional_seleccionada]

if "sitio_seleccionado" in globals() and sitio_seleccionado != "TODOS":
    df_filtrado = df_filtrado[df_filtrado["SITIO_UNINET"] == sitio_seleccionado]

if "modelo_seleccionado" in globals() and modelo_seleccionado != "TODOS":
    df_filtrado = df_filtrado[df_filtrado["MODELO_EQUIPO"] == modelo_seleccionado]

if "equipo_seleccionado" in globals() and equipo_seleccionado != "TODOS":
    df_filtrado = df_filtrado[df_filtrado["NOMBRE_EQUIPO"] == equipo_seleccionado]

# =====================================================================
# PROCESAMIENTO MATEMÁTICO: TABLA DINÁMICA (CROSSTAB)
# =====================================================================
if not df_filtrado.empty:
    # Creamos la tabla dinámica calculando las cantidades por cruce
    tabla_dinamica = pd.crosstab(
        index=df_filtrado["NOMBRE_EQUIPO"],
        columns=df_filtrado["NUM_PARTE_TARJETA"],
        margins=True,  # Agrega filas y columnas de totales
        margins_name="TOTAL GENERAL",
    )

    # Métricas rápidas superiores de control (Calculadas post-filtro)
    total_equipos_visibles = len(tabla_dinamica) - 1
    total_tarjetas_desplegadas = tabla_dinamica.loc[
        "TOTAL GENERAL", "TOTAL GENERAL"
    ]

    m1, m2 = st.columns(2)
    m1.metric("Equipos Incluidos en Matriz", f"{total_equipos_visibles:,}")
    m2.metric(
        "Suma Total Unidades Físicas", f"{int(total_tarjetas_desplegadas):,}"
    )

    st.markdown("---")

    # =====================================================================
    # RENDERIZADO DE LA TABLA DINÁMICA
    # =====================================================================
    st.subheader("📊 Distribución Matricial de Inventario")


    # Opciones estéticas avanzadas: Totales en negrita y resaltar celdas > 0
    def estilo_matriz_dinamica(df):
        # Crear un dataframe espejo vacío para los estilos CSS
        css_df = pd.DataFrame("", index=df.index, columns=df.columns)

        # 1. Recorrer celdas para aplicar color a valores mayores a 0 (omitir la fila/columna de totales)
        for col in df.columns:
            for idx in df.index:
                val = df.loc[idx, col]

                # Ignorar las etiquetas de totales para el pintado numérico
                if idx != "TOTAL GENERAL" and col != "TOTAL GENERAL":
                    if pd.notna(val) and val > 0:
                        # Color verde/azul suave con texto oscuro para celdas con tarjetas reales
                        css_df.loc[
                            idx, col] = "background-color: rgba(40, 167, 69, 0.15); color: #1e4620; font-weight: bold;"
                    else:
                        # Atenuar los ceros para limpiar el ruido visual de la tabla
                        css_df.loc[idx, col] = "color: #adb5bd; font-size: 0.9em;"

        # 2. Resaltar la última columna de totales generales
        if "TOTAL GENERAL" in df.columns:
            css_df["TOTAL GENERAL"] = "font-weight: bold; background-color: rgba(108, 117, 125, 0.12); color: #212529;"

        # 3. Resaltar la última fila de totales generales
        if "TOTAL GENERAL" in df.index:
            css_df.loc[
                "TOTAL GENERAL", :] = "font-weight: bold; background-color: rgba(108, 117, 125, 0.12); color: #212529;"

        return css_df


    # Renderizar la Pivot Table aplicando el nuevo estilo combinado
    st.dataframe(
        tabla_dinamica.style.apply(estilo_matriz_dinamica, axis=None),
        use_container_width=True,
        hide_index=False,
    )
