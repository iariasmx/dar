import io
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dar.db import crear_engine_mysql
from dar.graficas import mostrar_top_modelos
from dar.obsolescencia import cargar_catalogo_obsolescencia, detectar_piezas_obsoletas
from dar.resumen_hardware import mostrar_resumen_hardware
from dar.sesiones import mostrar_sesiones
from dar.sesiones import agregar_modelo_equipo, cargar_sesiones, filtrar_sesiones_por_equipos, preparar_sesiones
from dar.siru_vs_red import generar_matriz_conectividad

pd.set_option("styler.render.max_elements", 5000000)

# Configuración de la página de Streamlit
st.set_page_config(
    page_title="Dashboard de Inventario SIRU",
    page_icon="📊",
    layout="wide"
)

st.logo(
    image=str(PROJECT_ROOT / "assets" / "logo_uninet.png"),
    icon_image=str(PROJECT_ROOT / "assets" / "logo_uninet.png"),
    size="large"                   # Dimensión del contenedor web
)


# Función optimizada con caché para leer todos los datos de SIRU_DSL
@st.cache_data
def cargar_datos_siru():
    query = """
            SELECT ID_INTERNO, \
                   DIVISIONAL, \
                   SITIO_UNINET, \
                   NOMBRE_EQUIPO, \
                   UBICACION,
                   MODELO as MODELO_EQUIPO, \
                   FOLIO_DI_EQPO, \
                   STATUS_EQUIPO, \
                   LICENCIA,
                   FUNCIONALIDAD, \
                   NUM_PARTE_TARJETA, \
                   STATUS_TARJETA, \
                   NUM_PARTE_SUBTARJETA,
                   STATUS_SUBTARJETA, \
                   CHASIS, \
                   SLOT, \
                   SUBSLOT, \
                   PUERTO, \
                   PUERTO_GENERADO, \
                   TIPO_ASIG,
                   PISO, \
                   SALA, \
                   FILA, \
                   ELEMENTO_DE_FILA, \
                   PATCH_PANEL, \
                   POS_REMATE,
                   DESCRIPCION
            FROM SIRU_DSL
            WHERE NOMBRE_EQUIPO IS NOT NULL
              AND STATUS_EQUIPO != 'BAJA';
            """
    conexion = None
    try:
        # 1. Creamos el motor de conexión compatible con Pandas
        engine = crear_engine_mysql()

        # 2. Validamos la columna usando una conexión explícita de SQLAlchemy
        with engine.connect() as conn:
            result = conn.execute(text("SHOW COLUMNS FROM SIRU_DSL"))
            columnas = {fila[0].upper() for fila in result.fetchall()}

        # Compatibilidad con bases creadas antes de incorporar POS_REMATE
        if 'POS_REMATE' not in columnas:
            query = query.replace('POS_REMATE,', 'NULL AS POS_REMATE,')

        # 3. Ejecutamos pd.read_sql usando el 'engine' en lugar del driver crudo
        df = pd.read_sql(query, engine)
        return df

    except Exception as e:
        st.error(f"❌ Error al conectar o consultar MySQL (SIRU_DSL): {e}")
        return pd.DataFrame()


@st.cache_data
def cargar_datos_estatus_hardware():
    """Carga todos los estados de equipo, incluyendo equipos en BAJA."""
    query = """
            SELECT DIVISIONAL, SITIO_UNINET, NOMBRE_EQUIPO,
                   MODELO as MODELO_EQUIPO, STATUS_EQUIPO, CHASIS,
                   NUM_PARTE_TARJETA, STATUS_TARJETA, SLOT,
                   NUM_PARTE_SUBTARJETA, STATUS_SUBTARJETA, SUBSLOT
            FROM SIRU_DSL
            WHERE NOMBRE_EQUIPO IS NOT NULL;
            """
    try:
        return pd.read_sql(query, crear_engine_mysql())
    except Exception as e:
        st.error(f"❌ Error al consultar los estados de hardware en SIRU_DSL: {e}")
        return pd.DataFrame()


# Cargar detalles de interfaces L1
@st.cache_data
def cargar_datos_interfaces():
    query = """
            SELECT ID_INTERFACE, \
                   ID_EQUIPO, \
                   SLOT, \
                   SHUTDOWN, \
                   DESCRIPCION as DESC_L1, \
                   ANCHO_BANDA, \
                   PROTOCOLO, \
                   TIPO, \
                   IP_ADDRESS, \
                   STATUS      as STATUS_L1, \
                   VLAN, \
                   TRUNK, \
                   TRAFICO_95, \
                   OK_MET
            FROM EQUIPOS_DSL_INTERFACE_L1;
            """
    try:
        # Creamos el motor de conexión compatible con Pandas
        engine = crear_engine_mysql()

        # Ejecutamos pd.read_sql usando la tabla correcta EQUIPOS_DSL_INTERFACE_L1
        df = pd.read_sql(query, engine)
        return df

    except Exception as e:
        st.error(f"❌ Error al conectar o consultar MySQL (EQUIPOS_DSL_INTERFACE_L1): {e}")
        return pd.DataFrame()


# Nueva función para leer la tabla de equipos DSL desde MySQL
@st.cache_data
def cargar_datos_equipos_dsl():
    query = "SELECT * FROM EQUIPOS_DSL;"
    try:
        engine = crear_engine_mysql()
        df = pd.read_sql(query, engine)
        return df
    except Exception as e:
        st.error(f"❌ Error al conectar o consultar MySQL (EQUIPOS_DSL): {e}")
        return pd.DataFrame()


# Cargar DataFrames base globales
df_siru = cargar_datos_siru()
df_estatus_hardware_siru = cargar_datos_estatus_hardware()
df_interfaces = cargar_datos_interfaces()
df_equipos_dsl = cargar_datos_equipos_dsl()

if df_siru.empty:
    st.warning("⚠️ No se encontraron datos o la conexión a la base de datos falló.")
    st.stop()

# =====================================================================
# 2. LIMPIEZA Y NORMALIZACIÓN DE DATOS
# =====================================================================
df_siru['NUM_PARTE_TARJETA'] = df_siru['NUM_PARTE_TARJETA'].fillna('').str.strip()
df_siru['NUM_PARTE_SUBTARJETA'] = df_siru['NUM_PARTE_SUBTARJETA'].fillna('').str.strip()
df_siru['SLOT'] = df_siru['SLOT'].fillna('0').astype(str).str.strip()
df_siru['SUBSLOT'] = df_siru['SUBSLOT'].fillna('0').astype(str).str.strip()
df_siru['PUERTO'] = df_siru['PUERTO'].fillna('').str.strip()
df_siru['TIPO_ASIG'] = df_siru['TIPO_ASIG'].fillna('').str.strip().str.upper()


def preparar_estatus_hardware(df):
    """Normaliza equipo, tarjetas y subtarjetas en una tabla de estatus."""
    columnas = [
        'DIVISIONAL', 'SITIO_UNINET', 'NOMBRE_EQUIPO', 'MODELO_EQUIPO',
        'TIPO_COMPONENTE', 'NUM_PARTE', 'SLOT', 'SUBSLOT', 'ESTATUS',
    ]
    if df.empty:
        return pd.DataFrame(columns=columnas)

    registros = []
    datos_equipo = df.drop_duplicates(subset=['NOMBRE_EQUIPO'])
    for _, fila in datos_equipo.iterrows():
        registros.append({
            'DIVISIONAL': fila['DIVISIONAL'], 'SITIO_UNINET': fila['SITIO_UNINET'],
            'NOMBRE_EQUIPO': fila['NOMBRE_EQUIPO'], 'MODELO_EQUIPO': fila['MODELO_EQUIPO'],
            'TIPO_COMPONENTE': 'Equipo / chasis', 'NUM_PARTE': fila['CHASIS'],
            'SLOT': '', 'SUBSLOT': '', 'ESTATUS': fila['STATUS_EQUIPO'],
        })

    tarjetas = df[df['NUM_PARTE_TARJETA'].fillna('').str.strip().ne('')].drop_duplicates(
        subset=['NOMBRE_EQUIPO', 'SLOT', 'NUM_PARTE_TARJETA']
    )
    for _, fila in tarjetas.iterrows():
        registros.append({
            'DIVISIONAL': fila['DIVISIONAL'], 'SITIO_UNINET': fila['SITIO_UNINET'],
            'NOMBRE_EQUIPO': fila['NOMBRE_EQUIPO'], 'MODELO_EQUIPO': fila['MODELO_EQUIPO'],
            'TIPO_COMPONENTE': 'Tarjeta', 'NUM_PARTE': fila['NUM_PARTE_TARJETA'],
            'SLOT': fila['SLOT'], 'SUBSLOT': '', 'ESTATUS': fila['STATUS_TARJETA'],
        })

    subtarjetas = df[df['NUM_PARTE_SUBTARJETA'].fillna('').str.strip().ne('')].drop_duplicates(
        subset=['NOMBRE_EQUIPO', 'SLOT', 'SUBSLOT', 'NUM_PARTE_SUBTARJETA']
    )
    for _, fila in subtarjetas.iterrows():
        registros.append({
            'DIVISIONAL': fila['DIVISIONAL'], 'SITIO_UNINET': fila['SITIO_UNINET'],
            'NOMBRE_EQUIPO': fila['NOMBRE_EQUIPO'], 'MODELO_EQUIPO': fila['MODELO_EQUIPO'],
            'TIPO_COMPONENTE': 'Subtarjeta', 'NUM_PARTE': fila['NUM_PARTE_SUBTARJETA'],
            'SLOT': fila['SLOT'], 'SUBSLOT': fila['SUBSLOT'], 'ESTATUS': fila['STATUS_SUBTARJETA'],
        })

    resultado = pd.DataFrame(registros, columns=columnas)
    resultado['ESTATUS'] = resultado['ESTATUS'].fillna('').astype(str).str.strip().str.upper()
    resultado['SLOT'] = resultado['SLOT'].fillna('').astype(str).str.strip()
    resultado['SUBSLOT'] = resultado['SUBSLOT'].fillna('').astype(str).str.strip()
    return resultado


df_estatus_hardware = preparar_estatus_hardware(df_estatus_hardware_siru)

# Campos de ubicación física
for col in ['UBICACION']:
    df_siru[col] = df_siru[col].fillna('N/A').str.strip()

if not df_interfaces.empty:
    df_interfaces['SLOT'] = df_interfaces['SLOT'].fillna('0').astype(str).str.strip()
    df_interfaces['STATUS_L1'] = df_interfaces['STATUS_L1'].fillna('UNKNOWN').str.upper()
    df_interfaces['IP_ADDRESS'] = df_interfaces['IP_ADDRESS'].fillna('').str.strip()
    df_interfaces['VLAN'] = df_interfaces['VLAN'].fillna('').str.strip()

# =====================================================================
# 3. PROCESAMIENTO Y PREPARACIÓN DE MÉTRICAS (Módulos de Cruce)
# =====================================================================

# Pestaña 1: Agrupamiento para inventario de Hardware
df_tarjetas = df_siru[df_siru['NUM_PARTE_TARJETA'] != ''].drop_duplicates(
    subset=['NOMBRE_EQUIPO', 'SLOT', 'NUM_PARTE_TARJETA']
)
detalle_tarjetas = df_tarjetas.groupby(
    ['DIVISIONAL', 'SITIO_UNINET', 'NOMBRE_EQUIPO', 'MODELO_EQUIPO', 'SLOT', 'NUM_PARTE_TARJETA']
).size().reset_index(name='Cantidad')

df_subtarjetas = df_siru[df_siru['NUM_PARTE_SUBTARJETA'] != ''].drop_duplicates(
    subset=['NOMBRE_EQUIPO', 'SLOT', 'SUBSLOT', 'NUM_PARTE_SUBTARJETA']
)
detalle_subtarjetas = df_subtarjetas.groupby(
    ['NOMBRE_EQUIPO', 'SLOT', 'SUBSLOT', 'NUM_PARTE_SUBTARJETA']
).size().reset_index(name='Cantidad')

inventario_hardware = detalle_tarjetas.merge(
    detalle_subtarjetas, on=['NOMBRE_EQUIPO', 'SLOT'], how='left', suffixes=('_Tarjeta', '_Subtarjeta')
)
inventario_hardware.rename(columns={'NUM_PARTE_TARJETA': 'MODELO_TARJETA', 'NUM_PARTE_SUBTARJETA': 'MODELO_SUBTARJETA'},
                           inplace=True)
inventario_hardware['MODELO_SUBTARJETA'] = inventario_hardware['MODELO_SUBTARJETA'].fillna('N/A')
inventario_hardware['SUBSLOT'] = inventario_hardware['SUBSLOT'].fillna('N/A')

# Pestaña 2: Capacidad de Puertos
es_procesadora = (
    df_siru['NUM_PARTE_SUBTARJETA'].str.upper().str.startswith('RE-', na=False)
    | df_siru['NUM_PARTE_TARJETA'].str.upper().str.contains('RSP', regex=False, na=False)
    | df_siru['NUM_PARTE_TARJETA'].str.upper().str.startswith('ESR-', na=False)
    | df_siru['NUM_PARTE_TARJETA'].str.upper().str.startswith('JNP', na=False)
    | df_siru['NUM_PARTE_TARJETA'].str.upper().str.startswith('RE-S', na=False)
)
df_puertos_validos = df_siru[(df_siru['PUERTO'] != '') & ~es_procesadora].copy()
df_puertos_validos['Es_Libre'] = df_puertos_validos['TIPO_ASIG'].eq('LIBRE').astype(int)
df_puertos_validos['Es_Reservado'] = df_puertos_validos['TIPO_ASIG'].str.contains('RESERVADO', regex=False).astype(int)
df_puertos_validos['Es_Ocupado'] = (
    df_puertos_validos['Es_Libre'].eq(0)
    & df_puertos_validos['Es_Reservado'].eq(0)
    & df_puertos_validos['TIPO_ASIG'].notna()
    & ~df_puertos_validos['TIPO_ASIG'].isin(['', 'SIN TIPO_ASIG'])
).astype(int)

resumen_puertos_equipo = df_puertos_validos.groupby(
    ['DIVISIONAL', 'SITIO_UNINET', 'NOMBRE_EQUIPO', 'MODELO_EQUIPO']).agg(
    Puertos_Ocupados=('Es_Ocupado', 'sum'),
    Puertos_Libres=('Es_Libre', 'sum'),
    Puertos_Reservados=('Es_Reservado', 'sum'),
    Total_Puertos=('PUERTO', 'count')
).reset_index()

resumen_puertos_equipo['%_Ocupacion'] = (
    resumen_puertos_equipo['Puertos_Ocupados']
    / resumen_puertos_equipo['Total_Puertos'] * 100
).round(1)

# Pestaña 4: Datos únicos de ubicación física de chasis
df_ubicacion_equipos = df_siru.drop_duplicates(subset=['NOMBRE_EQUIPO']).copy()

# Pestaña 5: CONCILIACIÓN MAESTRA CRUZADA (Agrupación SIRU por Slot + Cruce L1)
resumen_siru_slot = df_siru.groupby(['DIVISIONAL', 'SITIO_UNINET', 'NOMBRE_EQUIPO', 'MODELO_EQUIPO', 'SLOT']).agg(
    Puertos_Asignados=('TIPO_ASIG', lambda x: (x != 'LIBRE').sum()),
    Puertos_Libres_Siru=('TIPO_ASIG', lambda x: (x == 'LIBRE').sum())
).reset_index()

df_conciliacion_maestra = pd.merge(resumen_siru_slot, df_interfaces, on='SLOT', how='inner')

# Lógica inteligente de discrepancias
df_conciliacion_maestra['Discrepancia'] = df_conciliacion_maestra.apply(
    lambda r: "⚠️ Alerta: Puerto asignado pero Interfaz Apagada" if (r['Puertos_Asignados'] > 0 and r['SHUTDOWN'] == 1)
    else ("⚠️ Alerta: Slot Libre con IP Asignada" if (r['Puertos_Asignados'] == 0 and r['IP_ADDRESS'] != '')
          else "✅ Operación Alineada"), axis=1
)

# =====================================================================
# 4. DISPOSITIVOS DE INTERFAZ GRÁFICA (STREAMLIT SIDEBAR)
# =====================================================================
st.title("📊 Diseño y Análisis de Red UniNet")

def limpiar_filtros():
    for clave in ('filtro_divisional', 'filtro_modelo', 'filtro_equipo'):
        st.session_state[clave] = 'TODOS'
    st.session_state['filtro_sitio'] = []
    st.session_state['filtro_ip_vlan'] = ''
    st.session_state.pop('tipo_asig_ocupados', None)
    st.session_state['sesiones_tipo'] = None


st.sidebar.header("🔍 Filtros de Búsqueda")
st.sidebar.button("Limpiar filtros", on_click=limpiar_filtros, key="limpiar_filtros")

# Filtros Jerárquicos en Cascada
lista_divisionales = ["TODOS"] + sorted(df_siru['DIVISIONAL'].unique().tolist())
divisional_seleccionada = st.sidebar.selectbox("Selecciona Divisional:", lista_divisionales, key="filtro_divisional")

if divisional_seleccionada != "TODOS":
    df_filtrado_sitios = df_siru[df_siru['DIVISIONAL'] == divisional_seleccionada]
else:
    df_filtrado_sitios = df_siru

if not isinstance(st.session_state.get('filtro_sitio'), list):
    st.session_state['filtro_sitio'] = []
lista_sitios = sorted(df_filtrado_sitios['SITIO_UNINET'].dropna().unique().tolist())
sitio_seleccionado = st.sidebar.multiselect(
    "Selecciona Sitio Uninet:",
    lista_sitios,
    key="filtro_sitio",
    placeholder="Todos los sitios",
)

if sitio_seleccionado:
    df_filtrado_equipos = df_filtrado_sitios[df_filtrado_sitios['SITIO_UNINET'].isin(sitio_seleccionado)]
else:
    df_filtrado_equipos = df_filtrado_sitios

lista_modelos = ["TODOS"] + sorted(df_filtrado_equipos['MODELO_EQUIPO'].dropna().unique().tolist())
modelo_seleccionado = st.sidebar.selectbox("Selecciona Modelo de Equipo:", lista_modelos, key="filtro_modelo")

if modelo_seleccionado != "TODOS":
    df_filtrado_equipos = df_filtrado_equipos[df_filtrado_equipos['MODELO_EQUIPO'] == modelo_seleccionado]

lista_equipos = ["TODOS"] + sorted(df_filtrado_equipos['NOMBRE_EQUIPO'].unique().tolist())
equipo_seleccionado = st.sidebar.selectbox("Selecciona Nombre de Equipo:", lista_equipos, key="filtro_equipo")

# ENRIQUECIMIENTO 1: Buscador global rápido (IP / VLAN)
st.sidebar.markdown("---")
st.sidebar.header("🎯 Buscador Técnico Directo")
buscar_ip_vlan = st.sidebar.text_input("Ingresa Dirección IP o ID de VLAN:", "", key="filtro_ip_vlan").strip()

# =====================================================================
# 5. RENDERIZADO DE LAS PESTAÑAS (TABS) CON FILTRADO APLICADO
# =====================================================================
tab_resumen, tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
    "📌 Resumen ejecutivo",
    "⚙️ Números de Parte de Hardware",
    "⚙️ Distribución de tarjetas",
    "🔌 Capacidad y Estado de Puertos",
    "🌐 Interfaces",
    "📍 Ubicación de equipos",
    "🔄 Conciliación (SIRU vs Red)",
    "👥 Sesiones Infinitum",
    "⚠️ Obsolescencia y reemplazos",
    "🚦 Estatus de hardware",
])


# Aplicación de los filtros estándar y del buscador global en cascada a los Dataframes de vista
def filtrar_dataframe(df_target, campo_div='DIVISIONAL', campo_sit='SITIO_UNINET', campo_eq='NOMBRE_EQUIPO'):
    df_res = df_target.copy()
    if divisional_seleccionada != "TODOS" and campo_div in df_res.columns:
        df_res = df_res[df_res[campo_div] == divisional_seleccionada]
    if sitio_seleccionado and campo_sit in df_res.columns:
        df_res = df_res[df_res[campo_sit].isin(sitio_seleccionado)]
    if modelo_seleccionado != "TODOS" and 'MODELO_EQUIPO' in df_res.columns:
        df_res = df_res[df_res['MODELO_EQUIPO'] == modelo_seleccionado]
    if equipo_seleccionado != "TODOS" and campo_eq in df_res.columns:
        df_res = df_res[df_res[campo_eq] == equipo_seleccionado]

    # Si el buscador rápido tiene texto, sobreescribe o añade un filtro estricto por IP o VLAN
    if buscar_ip_vlan:
        if 'IP_ADDRESS' in df_res.columns and 'VLAN' in df_res.columns:
            df_res = df_res[(df_res['IP_ADDRESS'].str.contains(buscar_ip_vlan, case=False)) |
                            (df_res['VLAN'].str.contains(buscar_ip_vlan, case=False))]
    return df_res


@st.dialog("Detalle de puertos", width="large")
def mostrar_detalle_puertos(detalle, estado):
    st.subheader(f"Puertos {estado}")
    if estado == 'ocupados':
        tipos = detalle['TIPO_ASIG'].fillna('')
        resumen_tipos = tipos.value_counts().rename_axis('TIPO_ASIG').reset_index(name='Puertos_Ocupados')
        resumen_tipos['TIPO_ASIG'] = resumen_tipos['TIPO_ASIG'].replace('', 'Sin TIPO_ASIG')
        st.markdown("**Ocupados por tipo de asignación**")
        st.dataframe(resumen_tipos, width='stretch', hide_index=True)
        tipo_seleccionado = st.selectbox(
            'Filtrar ocupados por TIPO_ASIG',
            options=[None] + sorted(tipos.unique().tolist()),
            format_func=lambda tipo: 'Todos los tipos' if tipo is None else (tipo or 'Sin TIPO_ASIG'),
            key='tipo_asig_ocupados',
        )
        if tipo_seleccionado is not None:
            detalle = detalle[tipos == tipo_seleccionado]
        detalle = detalle.copy()
        detalle['TIPO_ASIG'] = detalle['TIPO_ASIG'].fillna('').replace('', 'Sin TIPO_ASIG')
    st.caption(f"{len(detalle):,} puertos {estado} con los filtros actuales.")
    st.dataframe(
        detalle[[
            "DIVISIONAL", "SITIO_UNINET", "NOMBRE_EQUIPO", "MODELO_EQUIPO",
            "CHASIS", "SLOT", "SUBSLOT", "PUERTO", "TIPO_ASIG",
            "NUM_PARTE_TARJETA", "NUM_PARTE_SUBTARJETA",
            "PISO", "SALA", "FILA", "ELEMENTO_DE_FILA", "PATCH_PANEL", "POS_REMATE",
            "DESCRIPCION",
        ]],
        column_config={
            "PISO": "Piso",
            "SALA": "Sala",
            "FILA": "Fila",
            "ELEMENTO_DE_FILA": "Elemento de fila",
            "PATCH_PANEL": "PP",
            "POS_REMATE": "Posición de remate"
        },
        width="content",
        hide_index=True,
    )


# Dataframe dinámico para descargas unificadas en Sidebar
df_para_descargar = pd.DataFrame()

# Hallazgos compartidos por el resumen ejecutivo y la pestaña de obsolescencia.
try:
    catalogo_obsoleto = cargar_catalogo_obsolescencia()
    df_obsoletos = detectar_piezas_obsoletas(df_siru, catalogo_obsoleto)
    df_obsoletos = filtrar_dataframe(df_obsoletos)
except Exception as error:
    st.error(f"No fue posible cargar o comparar la matriz de homologación: {error}")
    df_obsoletos = pd.DataFrame()

# --- PESTAÑA INICIAL: RESUMEN EJECUTIVO ---
with tab_resumen:
    st.markdown("## 📌 Resumen ejecutivo")
    alcance = "Todos los registros" if equipo_seleccionado == "TODOS" else f"Equipo: {equipo_seleccionado}"
    if divisional_seleccionada != "TODOS":
        alcance = f"{divisional_seleccionada} · {alcance}"
    if sitio_seleccionado:
        sitios = ', '.join(sitio_seleccionado)
        alcance = f"{sitios} · {alcance}"
    if modelo_seleccionado != "TODOS":
        alcance = f"{modelo_seleccionado} · {alcance}"
    st.caption(f"{alcance}  ·  Los pronósticos de interfaces se generan bajo demanda en su pestaña.")

    df_resumen_activos = filtrar_dataframe(df_siru)
    df_resumen_puertos = filtrar_dataframe(resumen_puertos_equipo)
    df_resumen_estatus = filtrar_dataframe(df_estatus_hardware)
    df_resumen_ubicacion = filtrar_dataframe(df_ubicacion_equipos)
    df_resumen_obsoletos = df_obsoletos

    total_equipos = df_resumen_activos['NOMBRE_EQUIPO'].nunique()
    total_tarjetas = df_resumen_activos[
        df_resumen_activos['NUM_PARTE_TARJETA'].ne('')
    ].drop_duplicates(['NOMBRE_EQUIPO', 'SLOT', 'NUM_PARTE_TARJETA']).shape[0]
    total_subtarjetas = df_resumen_activos[
        df_resumen_activos['NUM_PARTE_SUBTARJETA'].ne('')
    ].drop_duplicates(['NOMBRE_EQUIPO', 'SLOT', 'SUBSLOT', 'NUM_PARTE_SUBTARJETA']).shape[0]
    total_puertos = int(df_resumen_puertos['Total_Puertos'].sum()) if not df_resumen_puertos.empty else 0
    puertos_ocupados = int(df_resumen_puertos['Puertos_Ocupados'].sum()) if not df_resumen_puertos.empty else 0
    puertos_libres = int(df_resumen_puertos['Puertos_Libres'].sum()) if not df_resumen_puertos.empty else 0
    puertos_reservados = int(df_resumen_puertos['Puertos_Reservados'].sum()) if not df_resumen_puertos.empty else 0
    ocupacion = (puertos_ocupados / total_puertos * 100) if total_puertos else 0

    sin_reemplazo = (
        int(df_resumen_obsoletos['REEMPLAZO_SUGERIDO'].fillna('').map(str.strip).eq('').sum())
        if not df_resumen_obsoletos.empty else 0
    )
    ubicaciones_pendientes = int(
        df_resumen_ubicacion['UBICACION'].fillna('').str.strip().isin(['', 'N/A']).sum()
    )
    conteo_estatus = (
        df_resumen_estatus['ESTATUS'].replace('', 'SIN ESTATUS').value_counts()
        .rename_axis('Estatus').reset_index(name='Componentes')
    )
    colores_estatus = {
        'EN SERVICIO': '#d9ead3',
        'PLANEADO': '#fff2cc',
        'BAJA PLANEADA': '#f4cccc',
        'BAJA': '#f4cccc',
    }

    # Franja de indicadores principales
    kpis = st.columns(4)
    for columna, etiqueta, valor in zip(
        kpis,
        ('Equipos activos', 'Tarjetas instaladas', 'Subtarjetas instaladas', 'Piezas obsoletas'),
        (total_equipos, total_tarjetas, total_subtarjetas, len(df_resumen_obsoletos)),
    ):
        with columna.container(border=True):
            st.metric(etiqueta, f"{valor:,}")

    st.markdown("### Equipos por modelo")
    with st.container(border=True):
        conteo_modelos = (
            df_resumen_activos[['NOMBRE_EQUIPO', 'MODELO_EQUIPO']]
            .drop_duplicates(subset=['NOMBRE_EQUIPO'])
            .assign(MODELO_EQUIPO=lambda datos: datos['MODELO_EQUIPO'].fillna('').replace('', 'SIN MODELO'))
            .groupby('MODELO_EQUIPO')['NOMBRE_EQUIPO']
            .nunique()
            .sort_values(ascending=False)
            .rename('Equipos')
            .reset_index()
        )
        if conteo_modelos.empty:
            st.info("No hay equipos para mostrar con los filtros actuales.")
        else:
            conteo_modelos['Porcentaje'] = conteo_modelos['Equipos'] / conteo_modelos['Equipos'].sum() * 100
            st.dataframe(
                conteo_modelos,
                hide_index=True,
                width="stretch",
                column_config={
                    'MODELO_EQUIPO': 'Modelo de equipo',
                    'Equipos': st.column_config.NumberColumn('Cantidad de equipos', format='%d'),
                    'Porcentaje': st.column_config.ProgressColumn(
                        'Proporción del inventario', format='%.1f%%', min_value=0, max_value=100
                    ),
                },
            )

    st.markdown("### Capacidad y ciclo de vida")
    col_puertos, col_estatus = st.columns([1.15, 1])
    with col_puertos:
        with st.container(border=True):
            st.markdown("#### 🔌 Capacidad de puertos")
            st.metric("Ocupación", f"{ocupacion:.1f}%", help=f"{puertos_ocupados:,} ocupados de {total_puertos:,} puertos")
            st.progress(min(max(ocupacion / 100, 0), 1))
            metricas_puerto = st.columns(3)
            metricas_puerto[0].metric("Ocupados", f"{puertos_ocupados:,}")
            metricas_puerto[1].metric("Libres", f"{puertos_libres:,}")
            metricas_puerto[2].metric("Reservados", f"{puertos_reservados:,}")
            st.caption(f"{total_puertos:,} puertos contabilizados en el alcance seleccionado.")

    with col_estatus:
        with st.container(border=True):
            st.markdown("#### 🚦 Estatus del hardware")
            if conteo_estatus.empty:
                st.info("No hay estatus disponibles para los filtros actuales.")
            else:
                st.dataframe(
                    conteo_estatus.style.map(
                        lambda valor: f"background-color: {colores_estatus.get(valor, '#f4cccc')};",
                        subset=['Estatus'],
                    ),
                    hide_index=True, width="stretch",
                )
            st.caption("Incluye equipos, tarjetas y subtarjetas, también los registros en BAJA.")

    st.markdown("### Hallazgos operativos")
    col_obsolescencia, col_inventario = st.columns([1.15, 1])
    with col_obsolescencia:
        with st.container(border=True):
            st.markdown("#### ⚠️ Obsolescencia y reemplazos")
            if df_resumen_obsoletos.empty:
                st.success("Sin piezas obsoletas detectadas en este alcance.")
            else:
                st.warning(
                    f"{len(df_resumen_obsoletos):,} piezas obsoletas · "
                    f"{sin_reemplazo:,} sin reemplazo indicado en la matriz."
                )
                st.dataframe(
                    df_resumen_obsoletos.groupby('TIPO_COMPONENTE').size()
                    .rename('Piezas obsoletas').reset_index(),
                    hide_index=True, width="stretch",
                )

    with col_inventario:
        with st.container(border=True):
            st.markdown("#### 📍 Calidad de ubicación")
            ubicacion_kpis = st.columns(2)
            ubicacion_kpis[0].metric("Equipos revisados", f"{len(df_resumen_ubicacion):,}")
            ubicacion_kpis[1].metric("Sin ubicación", f"{ubicaciones_pendientes:,}")
            st.caption(f"🌐 {len(df_interfaces):,} interfaces L1 registradas en la fuente.")

    st.markdown("### Uso de sesiones")
    # Las sesiones se resumen con el mismo conjunto de equipos que consume la pestaña Infinitum.
    try:
        equipos_sesiones_resumen = df_resumen_activos[['NOMBRE_EQUIPO', 'MODELO_EQUIPO']].drop_duplicates()
        datos_sesiones_resumen = preparar_sesiones(cargar_sesiones())
        datos_sesiones_resumen = filtrar_sesiones_por_equipos(
            datos_sesiones_resumen, equipos_sesiones_resumen['NOMBRE_EQUIPO'].dropna().unique().tolist()
        )
        datos_sesiones_resumen = agregar_modelo_equipo(datos_sesiones_resumen, equipos_sesiones_resumen)
        sesiones_validas = datos_sesiones_resumen['SESIONES'].dropna()
        with st.container(border=True):
            st.markdown("#### 👥 Sesiones Infinitum")
            sesion_kpis = st.columns(2)
            sesion_kpis[0].metric("Interfaces con dato", f"{len(sesiones_validas):,}")
            sesion_kpis[1].metric("Sesiones registradas", f"{int(sesiones_validas.sum()):,}")
    except Exception as error:
        st.info(f"No fue posible incluir las sesiones en este resumen: {error}")

    # Recomendaciones basadas en hallazgos observables, con prioridades operativas.
    st.markdown("### 🧭 Acciones sugeridas por ingeniería")
    acciones = []
    conteo_por_estatus = dict(zip(conteo_estatus['Estatus'], conteo_estatus['Componentes']))
    piezas_baja = int(conteo_por_estatus.get('BAJA', 0))
    piezas_baja_planeada = int(conteo_por_estatus.get('BAJA PLANEADA', 0))
    piezas_planeadas = int(conteo_por_estatus.get('PLANEADO', 0))
    sin_estatus = int(conteo_por_estatus.get('SIN ESTATUS', 0))

    if not df_resumen_obsoletos.empty:
        accion = (
            "Prioridad alta" if sin_reemplazo else "Prioridad media"
        )
        detalle = f"{len(df_resumen_obsoletos):,} piezas obsoletas"
        if sin_reemplazo:
            detalle += f"; {sin_reemplazo:,} sin reemplazo sugerido"
        acciones.append({
            'Prioridad': accion,
            'Acción recomendada': (
                "Validar el reemplazo con arquitectura y proveedor, revisar compatibilidad de software/slots "
                "y definir una ventana de migración con plan de reversa."
            ),
            'Hallazgo': detalle,
        })

    if piezas_baja:
        acciones.append({
            'Prioridad': 'Prioridad alta',
            'Acción recomendada': (
                "Conciliar estos activos dados de baja contra inventario y configuración de red; "
                "confirmar que no tengan servicios dependientes antes de retirarlos de los registros operativos."
            ),
            'Hallazgo': f"{piezas_baja:,} componentes con estatus BAJA",
        })
    if piezas_baja_planeada:
        acciones.append({
            'Prioridad': 'Planificación',
            'Acción recomendada': (
                "Acordar fecha de retiro, equipo sustituto, dependencias y ventana de cambio; "
                "mantener seguimiento hasta completar la baja."
            ),
            'Hallazgo': f"{piezas_baja_planeada:,} componentes con baja planeada",
        })
    if piezas_planeadas:
        acciones.append({
            'Prioridad': 'Planificación',
            'Acción recomendada': (
                "Confirmar alcance, responsable, disponibilidad y criterios de aceptación; "
                "actualizar el estatus cuando la instalación y validación queden concluidas."
            ),
            'Hallazgo': f"{piezas_planeadas:,} componentes planeados",
        })

    if not df_resumen_puertos.empty:
        capacidad_equipo = df_resumen_puertos.copy()
        capacidad_equipo['OCUPACION_PCT'] = (
            capacidad_equipo['Puertos_Ocupados']
            / capacidad_equipo['Total_Puertos'].replace(0, pd.NA)
            * 100
        )
        equipos_criticos = capacidad_equipo[capacidad_equipo['OCUPACION_PCT'] >= 95]
        equipos_alta_ocupacion = capacidad_equipo[
            (capacidad_equipo['OCUPACION_PCT'] >= 85)
            & (capacidad_equipo['OCUPACION_PCT'] < 95)
        ]
        if not equipos_criticos.empty:
            ejemplos = ', '.join(
                f"{fila.NOMBRE_EQUIPO} ({fila.OCUPACION_PCT:.0f}%)"
                for fila in equipos_criticos.nlargest(5, 'OCUPACION_PCT').itertuples()
            )
            acciones.append({
                'Prioridad': 'Prioridad alta',
                'Acción recomendada': (
                    "Revisar capacidad de inmediato: identificar puertos recuperables, validar crecimiento "
                    "de demanda y preparar expansión o redistribución antes de nuevas conexiones."
                ),
                'Hallazgo': f"{len(equipos_criticos):,} equipos con ocupación ≥95%: {ejemplos}",
            })
        elif not equipos_alta_ocupacion.empty:
            ejemplos = ', '.join(
                f"{fila.NOMBRE_EQUIPO} ({fila.OCUPACION_PCT:.0f}%)"
                for fila in equipos_alta_ocupacion.nlargest(5, 'OCUPACION_PCT').itertuples()
            )
            acciones.append({
                'Prioridad': 'Monitoreo',
                'Acción recomendada': (
                    "Incluir estos equipos en el pronóstico de capacidad y revisar mensualmente "
                    "la tendencia de crecimiento para anticipar ampliaciones."
                ),
                'Hallazgo': f"{len(equipos_alta_ocupacion):,} equipos entre 85% y 95%: {ejemplos}",
            })

    if ubicaciones_pendientes:
        acciones.append({
            'Prioridad': 'Calidad de datos',
            'Acción recomendada': (
                "Completar sitio y ubicación física (sala, fila y posición) en SIRU; "
                "esto facilita atención de incidentes, cambios y validaciones en campo."
            ),
            'Hallazgo': f"{ubicaciones_pendientes:,} equipos sin ubicación capturada",
        })
    if sin_estatus:
        acciones.append({
            'Prioridad': 'Calidad de datos',
            'Acción recomendada': "Completar y normalizar el estatus de los componentes para que los reportes de ciclo de vida sean confiables.",
            'Hallazgo': f"{sin_estatus:,} componentes sin estatus",
        })

    with st.container(border=True):
        if acciones:
            prioridad_orden = {'Prioridad alta': 0, 'Planificación': 1, 'Monitoreo': 2, 'Calidad de datos': 3, 'Prioridad media': 4}
            acciones.sort(key=lambda accion: prioridad_orden.get(accion['Prioridad'], 5))
            st.dataframe(
                pd.DataFrame(acciones),
                hide_index=True,
                width="stretch",
                column_config={
                    'Prioridad': st.column_config.TextColumn('Prioridad', width='small'),
                    'Acción recomendada': st.column_config.TextColumn('Acción recomendada', width='large'),
                    'Hallazgo': st.column_config.TextColumn('Dato que la sustenta', width='medium'),
                },
            )
        else:
            st.success(
                "No hay alertas que requieran una acción inmediata en este alcance. "
                "Mantén la revisión periódica de capacidad, obsolescencia, estados y calidad del inventario."
            )

# --- PESTAÑA 1: HARDWARE ---
with tab1:
    st.subheader("Matriz de Inventario y Números de Parte")
    df_tab1 = filtrar_dataframe(inventario_hardware)
    cols_t1 = [
        "DIVISIONAL",
        "SITIO_UNINET",
        "NOMBRE_EQUIPO",
        "MODELO_EQUIPO",
        "SLOT",
        "MODELO_TARJETA",
        "SUBSLOT",
        "MODELO_SUBTARJETA",
    ]
    st.dataframe(df_tab1[cols_t1], width="content", hide_index=True)

    col_g1, col_g2 = st.columns(2)
    with col_g1:
        st.markdown("Top Tarjetas Predominantes")
        mostrar_top_modelos(
            df_tab1["MODELO_TARJETA"].value_counts().head(10),
            key="app_top_tarjetas",
        )
    with col_g2:
        st.markdown("Top Subtarjetas Predominantes")
        mostrar_top_modelos(
            df_tab1[df_tab1["MODELO_SUBTARJETA"] != "N/A"][
                "MODELO_SUBTARJETA"
            ]
            .value_counts()
            .head(10),
            key="app_top_subtarjetas",
        )

# --- PESTAÑA 2: DISTRIBUCION ---
with tab2:
    st.subheader("Distribución de tarjetas por equipo")
    try:
        mostrar_resumen_hardware(
            divisional=divisional_seleccionada,
            sitio=sitio_seleccionado,
            modelo=modelo_seleccionado,
            equipo=equipo_seleccionado,
        )
    except Exception as e:
        st.error(f"💥 Error al mostrar el resumen: {e}")

# --- PESTAÑA 3: CAPACIDAD ---
with tab3:
    st.subheader("Análisis de Disponibilidad y Saturación de Puertos")
    df_tab3 = filtrar_dataframe(resumen_puertos_equipo)
    p_ocupados = df_tab3["Puertos_Ocupados"].sum()
    p_libres = df_tab3["Puertos_Libres"].sum()
    p_reservados = df_tab3["Puertos_Reservados"].sum()

    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric("🔴 Puertos Ocupados (Filtro)", f"{p_ocupados:,}")
    kpi2.metric("🟢 Puertos Libres (Disponibles)", f"{p_libres:,}")
    kpi3.metric("🟡 Puertos Reservados", f"{p_reservados:,}")
    for columna, estado, indicador, total in (
        (kpi1, "ocupados", "Es_Ocupado", p_ocupados),
        (kpi2, "libres", "Es_Libre", p_libres),
        (kpi3, "reservados", "Es_Reservado", p_reservados),
    ):
        if columna.button(
            f"Ver puertos {estado}",
            key=f"ver_puertos_{estado}",
            disabled=total == 0,
            help=f"Abre el detalle de los puertos {estado} con los filtros actuales.",
        ):
            # Usar los mismos grupos y la misma clasificación que el contador.
            claves_capacidad = ['DIVISIONAL', 'SITIO_UNINET', 'NOMBRE_EQUIPO', 'MODELO_EQUIPO']
            detalle = df_puertos_validos[
                df_puertos_validos[indicador] == 1
            ].merge(df_tab3[claves_capacidad], on=claves_capacidad, how='inner', validate='many_to_one')
            mostrar_detalle_puertos(detalle, estado)

    st.markdown("---")
    st.markdown("Detalle de Capacidad por Chasis")
    st.dataframe(
        df_tab3[
            [
                "DIVISIONAL",
                "SITIO_UNINET",
                "NOMBRE_EQUIPO",
                "MODELO_EQUIPO",
                "Puertos_Ocupados",
                "Puertos_Libres",
                "Puertos_Reservados",
                "Total_Puertos",
                "%_Ocupacion",
            ]
        ],
        column_config={
            "%_Ocupacion": st.column_config.ProgressColumn(
                "Porcentaje de Ocupación",
                format="%.1f%%",
                min_value=0.0,
                max_value=100.0,
            )
        },
        width="content",
        hide_index=True,
    )

# --- PESTAÑA 4: CAPA INTERFACES L1 (PRONÓSTICOS) ---
with tab4:
    st.subheader("🔮 Análisis Predictivo de Tendencias (Capacidad L1)")
    st.markdown(
        "Proyección inteligente de saturación y capacidad de enlaces de red mediante aprendizaje estadístico utilizando **Prophet**.")

    # 1. Validación de los Filtros de la Barra Lateral Jerárquica
    if equipo_seleccionado == "TODOS":
        st.warning(
            "⚠️ Selecciona un **Nombre de Equipo** específico en la barra lateral para inspeccionar sus interfaces y tendencias históricas.")
    else:
        from dar import pronosticos
        import pandas as pd

        # 2. Extracción dinámica de hostnames basados en el equipo PERCENTIL_HISTORICO actual
        try:
            with st.spinner("Buscando interfaces indexadas en telemetría..."):
                engine_prophet = crear_engine_mysql()
                query_buscar_hosts = """
                                     SELECT DISTINCT interface_hostname
                                     FROM PERCENTIL_HISTORICO
                                     WHERE interface_hostname LIKE %s
                                        OR interface_hostname = %s
                                     ORDER BY interface_hostname; \
                                     """
                patron_busqueda = f"%{equipo_seleccionado}%"
                df_hosts_disponibles = pd.read_sql(
                    query_buscar_hosts,
                    engine_prophet,
                    params=(patron_busqueda, equipo_seleccionado)
                )
            error_telemetria = None
        except Exception as error:
            df_hosts_disponibles = pd.DataFrame()
            error_telemetria = error

        if error_telemetria:
            if "1146" in str(error_telemetria) or "doesn't exist" in str(error_telemetria):
                st.warning(
                    "La tabla `PERCENTIL_HISTORICO` no existe en la base de datos configurada. "
                    "La pestaña de pronósticos estará disponible cuando se cree y alimente esa tabla."
                )
            else:
                st.error(f"No fue posible consultar la telemetría histórica: {error_telemetria}")
        elif df_hosts_disponibles.empty:
            st.error(
                f"❌ No se localizaron registros de tráfico históricos en `PERCENTIL_HISTORICO` para el equipo **{equipo_seleccionado}**.")
        else:
            # 3. Parametrización interactiva local de la pestaña
            col_l1, col_l2, col_l3 = st.columns(3)

            with col_l1:
                host_seleccionado = st.selectbox(
                    "Selecciona la Interfaz / Hostname de Red:",
                    options=df_hosts_disponibles['interface_hostname'].tolist(),
                    key="predict_host_l1"
                )

            with col_l2:
                # LISTA ACTUALIZADA CON LOS NOMBRES DEL DDL ACTUAL
                metrica_seleccionada = st.selectbox(
                    "Métrica de Rendimiento a Evaluar:",
                    options=[
                        "95_percentil_out_porcentaje",
                        "95_percentil_in_porcentaje",
                        "98_percentil_out_porcentaje",
                        "98_percentil_in_porcentaje",
                        "peak_out_porcentaje",
                        "peak_in_porcentaje"
                    ],
                    format_func=lambda x: x.replace("_", " ").title(),
                    key="predict_metric_l1"
                )

            with col_l3:
                horizonte_semanas = st.slider(
                    "Horizonte del Pronóstico (Semanas):",
                    min_value=4, max_value=26, value=12,
                    key="predict_weeks_l1"
                )

            btn_calcular_tendencia = st.button("🔮 Generar Pronóstico de Tendencia", use_container_width=True,
                                               type="primary")

            # 4. Inferencia Matemática y Visualización de Resultados
            if btn_calcular_tendencia:
                with st.spinner(
                        f"Analizando comportamiento histórico y entrenando Prophet para {host_seleccionado}..."):

                    # Llamada a la extracción limpia usando la variable local única df_telemetria_l1
                    df_telemetria_l1 = pronosticos.obtener_y_limpiar_datos(host_seleccionado, metrica_seleccionada,
                                                                           engine_prophet)

                    if df_telemetria_l1.empty:
                        st.warning(
                            f"La interfaz {host_seleccionado} no cuenta con registros de datos válidos para la métrica seleccionada.")
                    else:
                        modelo, forecast = pronosticos.generar_prediccion_prophet(df_telemetria_l1, horizonte_semanas)

                        if forecast is None:
                            st.error(
                                "⚠️ Datos históricos insuficientes (mínimo 2 semanas con datos en la DB) para poder proyectar una tendencia.")
                        else:
                            # Feedback informativo al usuario según la naturaleza de sus datos históricos
                            if modelo == "CONSTANTE":
                                st.info(
                                    "💡 **Nota de Tráfico:** Esta interfaz presenta un comportamiento completamente plano o sin consumo en todo su histórico. El pronóstico se proyecta constante.")
                            elif len(df_telemetria_l1) < 26:
                                st.info(
                                    "📊 **Nota de Precisión:** El histórico disponible es menor a 6 meses. La tendencia proyectada es lineal básica (sin curvas estacionales anuales).")
                            else:
                                st.success("¡Modelo predictivo generado con éxito!")

                            # 5. Renderizado de Gráfica Continua
                            # ======================================================================
                            # 🔥 NUEVA SECCIÓN: CÁLCULO E INTEGRACIÓN DE KPIS MÉRICOS DIGITALES
                            # ======================================================================
                            # Filtramos únicamente los registros del futuro para buscar el peor escenario real
                            df_solo_futuro = forecast[forecast['ds'] > df_telemetria_l1['ds'].max()]

                            if not df_solo_futuro.empty:
                                # Localizamos la fila con el pico más alto estimado (Peor Escenario)
                                fila_pico_max = df_solo_futuro.loc[df_solo_futuro['yhat_upper'].idxmax()]

                                valor_pico_max = fila_pico_max['yhat_upper']
                                fecha_pico_max = fila_pico_max['ds'].strftime('%Y-%m-%d')

                                # Obtenemos el último valor histórico real como referencia para comparar
                                ultimo_valor_real = df_telemetria_l1['y'].iloc[-1]
                                delta_crecimiento = valor_pico_max - ultimo_valor_real

                                # Desplegamos los KPIs en 3 columnas arriba del gráfico
                                col_kpi1, col_kpi2, col_kpi3 = st.columns(3)

                                with col_kpi1:
                                    st.metric(
                                        label="Pico Máximo Estimado",
                                        value=f"{valor_pico_max:.2f} %",
                                        delta=f"{delta_crecimiento:+.2f} % vs Último Real",
                                        delta_color="inverse"  # Rojo si sube, verde si baja (ideal para saturación)
                                    )

                                with col_kpi2:
                                    st.metric(
                                        label="📅 Fecha Estimada del Pico",
                                        value=fecha_pico_max
                                    )

                                with col_kpi3:
                                    # Estado del enlace basado en si el peor escenario cruza el 85%
                                    estado_enlace = "🚨 SATURACIÓN" if valor_pico_max > 85.0 else "✅ SEGURO"
                                    st.metric(
                                        label="Status de Capacidad Futura",
                                        value=estado_enlace
                                    )
                            st.markdown("---")
                            # ======================================================================

                            # 5. Renderizado de Gráfica Continua (Con Peor Escenario de Picos)
                            st.subheader("📈 Proyección de Tráfico con Intervalo de Picos Máximos")

                            chart_data = forecast[['ds', 'yhat', 'yhat_upper']].merge(df_telemetria_l1, on='ds',
                                                                                      how='left')
                            chart_data.rename(columns={
                                'y': 'Histórico Real (%)',
                                'yhat': 'Tendencia Promedio (%)',
                                'yhat_upper': 'Peor Escenario (Picos Máximos) (%)'
                            }, inplace=True)

                            chart_data.set_index('ds', inplace=True)
                            chart_data['Umbral Crítico (85%)'] = 85.0

                            st.line_chart(
                                chart_data[[
                                    'Histórico Real (%)',
                                    'Tendencia Promedio (%)',
                                    'Peor Escenario (Picos Máximos) (%)',
                                    'Umbral Crítico (85%)'
                                ]],
                                color=["#1f77b4", "#aec7e8", "#ff7f0e", "#d62728"]
                            )

                            # 6. Matriz Futura de Capacidad con Semáforo de Riesgo (>85%)
                            st.subheader("📋 Proyección Semanal Futura e Indicadores de Riesgo")

                            df_futuro = forecast[forecast['ds'] > df_telemetria_l1['ds'].max()][
                                ['ds', 'yhat', 'yhat_upper']].copy()
                            df_futuro.columns = ['Fecha Proyectada', 'Consumo Promedio Estimado (%)',
                                                 'Peor Escenario (Saturación Máxima) (%)']


                            # Marcado de alerta si el peor escenario matemático roza el umbral crítico
                            def estilo_alerta_saturacion(val):
                                if val > 85.0:
                                    return 'background-color: rgba(235, 74, 91, 0.2); color: #eb4a5b; font-weight: bold;'
                                else:
                                    # Formato CSS válido para celdas normales sin alerta
                                    return 'background-color: transparent;'


                            st.dataframe(
                                df_futuro.style.map(estilo_alerta_saturacion,
                                                    subset=['Peor Escenario (Saturación Máxima) (%)']).format(
                                    precision=2),
                                use_container_width=True,
                                hide_index=True
                            )
                            st.caption(
                                "💡 Nota: El indicador del **Peor Escenario** calcula el límite superior del intervalo de confianza. Las celdas marcadas señalan semanas de riesgo latente de saturación (>85%).")

# --- PESTAÑA 5: INFRAESTRUCTURA Y LOCALIZACIÓN ---
with tab5:
    st.subheader("📍 Localización en sitio")
    df_tab5 = filtrar_dataframe(df_ubicacion_equipos)
    cols_t4 = [
        "DIVISIONAL",
        "SITIO_UNINET",
        "NOMBRE_EQUIPO",
        "MODELO_EQUIPO",
        "UBICACION",
        "STATUS_EQUIPO",
        "FUNCIONALIDAD",
        "LICENCIA",
    ]
    st.dataframe(df_tab5[cols_t4], width="content", hide_index=True)

# --- PESTAÑA 6: CONCILIACIÓN DE TABLAS (CRUCE DIRECTO) ---
with tab6:
    # st.subheader("🔄 Diagnóstico Cruzado de Integridad Operativa")
    # st.markdown(
    #     "Análisis automático cruzando las asignaciones lógicas de "
    #     "SIRU_DSL y estados de capa física de INTERFACE_L1 indexados por Slot."
    # )
    generar_matriz_conectividad(
        df_siru=df_siru,
        df_equipos=df_equipos_dsl,
        df_interfaces=df_interfaces,
        divisional=divisional_seleccionada,
        sitio=sitio_seleccionado,
        modelo=modelo_seleccionado,
        equipo=equipo_seleccionado
    )

with tab7:
    equipos_sesiones = filtrar_dataframe(df_siru)[[
        'NOMBRE_EQUIPO',
        'MODELO_EQUIPO',
        'SLOT',
        'PUERTO',
        'NUM_PARTE_SUBTARJETA',
    ]].drop_duplicates()
    mostrar_sesiones(equipos_sesiones)

with tab8:
    st.subheader("Piezas obsoletas y reemplazos de la matriz UniNet")
    st.caption(
        "Cruce exacto de números de parte de chasis, tarjetas y subtarjetas contra las filas "
        "marcadas como OBSOLETO en la matriz."
    )
    if buscar_ip_vlan:
        st.caption("El buscador de IP/VLAN no aplica a este reporte de hardware.")
    if df_obsoletos.empty:
        st.info("No se encontraron piezas obsoletas instaladas con los filtros actuales.")
    else:
        reemplazos_vacios = df_obsoletos["REEMPLAZO_SUGERIDO"].fillna("").map(str.strip).eq("")
        kpi_obsoletos, kpi_partes, kpi_sin_reemplazo = st.columns(3)
        kpi_obsoletos.metric("Piezas instaladas obsoletas", f"{len(df_obsoletos):,}")
        kpi_partes.metric("Números de parte", f"{df_obsoletos['NUM_PARTE_INSTALADA'].nunique():,}")
        kpi_sin_reemplazo.metric("Sin reemplazo indicado", f"{int(reemplazos_vacios.sum()):,}")

        df_vista_obsoletos = df_obsoletos.copy()
        df_vista_obsoletos["REEMPLAZO_SUGERIDO"] = (
            df_vista_obsoletos["REEMPLAZO_SUGERIDO"].fillna("").replace("", "Sin reemplazo indicado")
        )
        columnas_obsoletos = [
            "DIVISIONAL", "SITIO_UNINET", "NOMBRE_EQUIPO", "MODELO_EQUIPO", "CHASIS",
            "TIPO_COMPONENTE", "SLOT", "SUBSLOT", "NUM_PARTE_INSTALADA",
            "PROVEEDOR_MATRIZ", "MODELO_MATRIZ", "TIPO_PIEZA_MATRIZ",
            "REEMPLAZO_SUGERIDO", "DESCRIPCION_MATRIZ", "HOJA_MATRIZ",
        ]
        st.dataframe(
            df_vista_obsoletos[columnas_obsoletos],
            width="stretch",
            hide_index=True,
            column_config={
                "TIPO_COMPONENTE": "Componente instalado",
                "NUM_PARTE_INSTALADA": "Número de parte instalado",
                "REEMPLAZO_SUGERIDO": "Reemplazo según matriz",
                "DESCRIPCION_MATRIZ": "Descripción en matriz",
                "HOJA_MATRIZ": "Hoja de origen",
            },
        )
        st.download_button(
            "Descargar reporte de obsolescencia (.csv)",
            data=df_vista_obsoletos[columnas_obsoletos].to_csv(index=False).encode("utf-8-sig"),
            file_name="reporte_hardware_obsoleto.csv",
            mime="text/csv",
        )

with tab9:
    st.subheader("Estatus de equipos, tarjetas y subt tarjetas")
    st.caption(
        "Los equipos en BAJA también se incluyen en esta vista. Verde: EN SERVICIO; "
        "amarillo: PLANEADO; rojo: BAJA PLANEADA o BAJA."
    )
    df_tab9 = filtrar_dataframe(df_estatus_hardware)
    if buscar_ip_vlan:
        st.caption("El buscador de IP/VLAN no aplica a este reporte de hardware.")
    if df_tab9.empty:
        st.info("No se encontraron componentes con los filtros actuales.")
    else:
        def estilo_estatus(valor):
            if valor == "EN SERVICIO":
                return "background-color: #d9ead3;"
            if valor == "PLANEADO":
                return "background-color: #fff2cc;"
            return "background-color: #f4cccc;"

        st.dataframe(
            df_tab9.style.map(estilo_estatus, subset=["ESTATUS"]),
            width="stretch",
            hide_index=True,
            column_config={
                "TIPO_COMPONENTE": "Componente",
                "NUM_PARTE": "Número de parte",
                "ESTATUS": "Estatus",
            },
        )


# =====================================================================
# ENRIQUECIMIENTO 2: MÓDULO DE DESCARGA AVANZADO EN SIDEBAR
# =====================================================================
if not df_para_descargar.empty:
    st.sidebar.markdown("---")
    st.sidebar.subheader("📥 Exportar Datos")

    # Generador de memoria en buffer para descarga directa en formato CSV
    csv_buffer = io.StringIO()
    df_para_descargar.to_csv(csv_buffer, index=False)
    csv_bytes = csv_buffer.getvalue().encode("utf-8")

    st.sidebar.download_button(
        label="💾 Descargar Conciliación Filtrada (.csv)",
        data=csv_bytes,
        file_name="conciliacion_siru_vs_l1.csv",
        mime="text/csv",
        help=(
            "Descarga el archivo estructurado con los filtros aplicados "
            "en el panel para auditoría externa."
        ),
    )
