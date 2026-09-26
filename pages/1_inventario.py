import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dar.db import conectar_mysql
from dar.graficas import mostrar_top_modelos

# Configuración de la página de Streamlit (Debe ser la primera instrucción)
st.set_page_config(
    page_title="Dashboard de Inventario SIRU",
    page_icon="📊",
    layout="wide"
)


# Función optimizada con caché para leer los datos de MySQL
@st.cache_data
def cargar_datos_siru():
    query = """
            SELECT SITIO_UNINET, \
                   NOMBRE_EQUIPO, \
                   MODELO as MODELO_EQUIPO, \
                   SLOT, \
                   NUM_PARTE_TARJETA, \
                   SUBSLOT, \
                   NUM_PARTE_SUBTARJETA, \
                   STATUS_EQUIPO
            FROM SIRU_DSL
            WHERE NOMBRE_EQUIPO IS NOT NULL
              AND STATUS_EQUIPO != 'BAJA'; \
            """
    try:
        conexion = conectar_mysql()
        df = pd.read_sql(query, conexion)
        conexion.close()
        return df
    except Exception as e:
        st.error(f"❌ Error al conectar o consultar MySQL: {e}")
        return pd.DataFrame()


# Cargar el DataFrame base
df_siru = cargar_datos_siru()

if df_siru.empty:
    st.warning("⚠️ No se encontraron datos o la conexión a la base de datos falló.")
    st.stop()

# =====================================================================
# LIMPIEZA Y NORMALIZACIÓN DE HARDWARE
# =====================================================================
df_siru['NUM_PARTE_TARJETA'] = df_siru['NUM_PARTE_TARJETA'].fillna('').str.strip()
df_siru['NUM_PARTE_SUBTARJETA'] = df_siru['NUM_PARTE_SUBTARJETA'].fillna('').str.strip()
df_siru['SLOT'] = df_siru['SLOT'].fillna('0')
df_siru['SUBSLOT'] = df_siru['SUBSLOT'].fillna('0')

# =====================================================================
# ANALISIS Y DETALLE DE MODELOS DE TARJETAS
# =====================================================================

# --- REPORTE 1: Modelos de Tarjetas por Equipo ---
df_tarjetas = df_siru[df_siru['NUM_PARTE_TARJETA'] != ''].drop_duplicates(
    subset=['NOMBRE_EQUIPO', 'SLOT', 'NUM_PARTE_TARJETA']
)

detalle_tarjetas = df_tarjetas.groupby(
    ['SITIO_UNINET', 'NOMBRE_EQUIPO', 'MODELO_EQUIPO', 'SLOT', 'NUM_PARTE_TARJETA']
).size().reset_index(name='Cantidad')

# --- REPORTE 2: Modelos de Subtarjetas por Equipo ---
df_subtarjetas = df_siru[df_siru['NUM_PARTE_SUBTARJETA'] != ''].drop_duplicates(
    subset=['NOMBRE_EQUIPO', 'SLOT', 'SUBSLOT', 'NUM_PARTE_SUBTARJETA']
)

detalle_subtarjetas = df_subtarjetas.groupby(
    ['NOMBRE_EQUIPO', 'SLOT', 'SUBSLOT', 'NUM_PARTE_SUBTARJETA']
).size().reset_index(name='Cantidad')

# --- REPORTE 3: Consolidado Maestro para el Dashboard ---
inventario_hardware = detalle_tarjetas.merge(
    detalle_subtarjetas,
    on=['NOMBRE_EQUIPO', 'SLOT'],
    how='left',
    suffixes=('_Tarjeta', '_Subtarjeta')
)

# Renombrar columnas para máxima claridad en el reporte
inventario_hardware.rename(columns={
    'NUM_PARTE_TARJETA': 'MODELO_TARJETA',
    'NUM_PARTE_SUBTARJETA': 'MODELO_SUBTARJETA'
}, inplace=True)

# Rellenar espacios vacíos donde no existan subtarjetas instaladas en la tarjeta
inventario_hardware['MODELO_SUBTARJETA'] = inventario_hardware['MODELO_SUBTARJETA'].fillna('N/A')
inventario_hardware['SUBSLOT'] = inventario_hardware['SUBSLOT'].fillna('N/A')
inventario_hardware['Cantidad_Subtarjeta'] = inventario_hardware['Cantidad_Subtarjeta'].fillna(0).astype(int)

# =====================================================================
# INTERFAZ GRÁFICA INTERACTIVA (STREAMLIT)
# =====================================================================

st.title("📊 Análisis de Hardware de Red (SIRU)")
st.markdown("Analizador de números de parte de tarjetas y subtarjetas instaladas en la infraestructura.")

# Indicadores clave en la parte superior (KPIs)
total_sitios = inventario_hardware['SITIO_UNINET'].nunique()
total_equipos = inventario_hardware['NOMBRE_EQUIPO'].nunique()
tarjetas_unicas = inventario_hardware['MODELO_TARJETA'].nunique()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric(label="📍 Total de Sitios Uninet", value=total_sitios)
with col2:
    st.metric(label="🖥️  Equipos Activos Evaluados", value=total_equipos)
with col3:
    st.metric(label="🛠️  Variedad de Modelos/Números de Parte de Tarjeta", value=tarjetas_unicas)

st.divider()

# Sección de Filtros Dinámicos (Barra Lateral)
st.sidebar.header("🔍 Filtros de Búsqueda")

# Filtro por Sitio Uninet
lista_sitios = ["TODOS"] + sorted(inventario_hardware['SITIO_UNINET'].unique().tolist())
sitio_seleccionado = st.sidebar.selectbox("Selecciona Sitio Uninet:", lista_sitios)

# Filtrar dataframe base temporalmente para actualizar la lista de equipos en cascada
if sitio_seleccionado != "TODOS":
    df_filtrado_sitio = inventario_hardware[inventario_hardware['SITIO_UNINET'] == sitio_seleccionado]
else:
    df_filtrado_sitio = inventario_hardware

# Filtro por modelo dentro del sitio seleccionado
lista_modelos = ["TODOS"] + sorted(df_filtrado_sitio['MODELO_EQUIPO'].dropna().unique().tolist())
modelo_seleccionado = st.sidebar.selectbox("Selecciona Modelo de Equipo:", lista_modelos)

if modelo_seleccionado != "TODOS":
    df_filtrado_sitio = df_filtrado_sitio[df_filtrado_sitio['MODELO_EQUIPO'] == modelo_seleccionado]

# Filtro por Nombre de Equipo
lista_equipos = ["TODOS"] + sorted(df_filtrado_sitio['NOMBRE_EQUIPO'].unique().tolist())
equipo_seleccionado = st.sidebar.selectbox("Selecciona Nombre de Equipo:", lista_equipos)

# Aplicar los filtros finales a la matriz de hardware
df_dashboard = inventario_hardware.copy()

if sitio_seleccionado != "TODOS":
    df_dashboard = df_dashboard[df_dashboard['SITIO_UNINET'] == sitio_seleccionado]

if modelo_seleccionado != "TODOS":
    df_dashboard = df_dashboard[df_dashboard['MODELO_EQUIPO'] == modelo_seleccionado]

if equipo_seleccionado != "TODOS":
    df_dashboard = df_dashboard[df_dashboard['NOMBRE_EQUIPO'] == equipo_seleccionado]

# Despliegue de los Resultados Filtrados
st.subheader("🗂️ Matrices de Análisis de Hardware")

col_tabla1, col_tabla2 = st.columns([0.55, 0.45])

with col_tabla1:
    st.markdown("**1. Detalle General por Ranura / Slot**")
    columnas_vista = [
        'SITIO_UNINET', 'NOMBRE_EQUIPO', 'MODELO_EQUIPO',
        'SLOT', 'MODELO_TARJETA', 'SUBSLOT', 'MODELO_SUBTARJETA'
    ]
    st.dataframe(
        df_dashboard[columnas_vista],
        use_container_width=True,
        hide_index=True
    )

with col_tabla2:
    st.markdown("**2. Resumen de Números de Parte Únicos por Slot**")

    # 🚀 CORRECCIÓN AQUÍ:
    # Primero colapsamos el dataframe para quedarnos solo con Tarjetas Únicas (borrando la inflación de subtarjetas)
    df_tarjetas_unicas = df_dashboard.drop_duplicates(
        subset=['NOMBRE_EQUIPO', 'SLOT', 'MODELO_TARJETA']
    )

    # Ahora sí, la agrupación contará TARJETAS físicas reales
    df_agrupado_slots = df_tarjetas_unicas.groupby(
        ['MODELO_TARJETA', 'SLOT']
    ).size().reset_index(name='Total Instalado')

    # Ordenar de forma limpia
    df_agrupado_slots = df_agrupado_slots.sort_values(by=['MODELO_TARJETA', 'SLOT'])

    st.dataframe(
        df_agrupado_slots,
        use_container_width=True,
        hide_index=True,
        column_config={
            "MODELO_TARJETA": "Número de Parte (Tarjeta)",
            "SLOT": "Slot",
            "Total Instalado": "Cantidad de Tarjetas Físicas"
        }
    )

# Sección Secundaria: Distribución de Hardware Común
st.divider()
st.subheader("📈 Top 10 Números de Parte Más Utilizados en la Red")

col_grafica1, col_grafica2 = st.columns(2)

with col_grafica1:
    st.markdown("**Modelos de Tarjeta Predominantes**")
    top_tarjetas = inventario_hardware['MODELO_TARJETA'].value_counts().head(10)
    mostrar_top_modelos(top_tarjetas, key="inventario_top_tarjetas")

with col_grafica2:
    st.markdown("**Modelos de Subtarjeta Predominantes**")
    # Excluimos N/A para graficar solo subtarjetas reales
    df_sub_reales = inventario_hardware[inventario_hardware['MODELO_SUBTARJETA'] != 'N/A']
    top_subtarjetas = df_sub_reales['MODELO_SUBTARJETA'].value_counts().head(10)
    mostrar_top_modelos(top_subtarjetas, key="inventario_top_subtarjetas")
