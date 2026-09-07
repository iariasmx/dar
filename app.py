import streamlit as st
import mysql.connector
import pandas as pd
import io

from config import db_config
from graficas import mostrar_top_modelos
from sesiones import mostrar_sesiones

# Configuración de la página de Streamlit
st.set_page_config(
    page_title="Dashboard de Inventario SIRU",
    page_icon="📊",
    layout="wide"
)

st.logo(
    image="logo_uninet.png",       # Logotipo local para barra lateral expandida
    icon_image="logo_uninet.png",  # Logotipo local si la barra lateral se colapsa
    size="large"                   # Dimensión del contenedor web
)


# Función optimizada con caché para leer todos los datos maestros de SIRU_DSL
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
        conexion = mysql.connector.connect(**db_config)
        # Compatibilidad con bases creadas antes de incorporar POS_REMATE.
        with conexion.cursor() as cursor:
            cursor.execute("SHOW COLUMNS FROM SIRU_DSL")
            columnas = {fila[0].upper() for fila in cursor.fetchall()}
        if 'POS_REMATE' not in columnas:
            query = query.replace('POS_REMATE,', 'NULL AS POS_REMATE,')
        df = pd.read_sql(query, conexion)
        return df
    except Exception as e:
        st.error(f"❌ Error al conectar o consultar MySQL (SIRU_DSL): {e}")
        return pd.DataFrame()
    finally:
        if conexion is not None:
            conexion.close()


# Cargar detalles de interfaces L1
@st.cache_data
def cargar_datos_interfaces():
    query = """
            SELECT SLOT, \
                   SHUTDOWN, \
                   DESCRIPCION as DESC_L1, \
                   ANCHO_BANDA, \
                   PROTOCOLO,
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
        conexion = mysql.connector.connect(**db_config)
        df = pd.read_sql(query, conexion)
        conexion.close()
        return df
    except Exception as e:
        st.error(f"❌ Error al consultar EQUIPOS_DSL_INTERFACE_L1: {e}")
        return pd.DataFrame()


# Cargar DataFrames base globales
df_siru = cargar_datos_siru()
df_interfaces = cargar_datos_interfaces()

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
st.title("📊 Análisis de Infraestructura y Capacidad (SIRU)")

def limpiar_filtros():
    for clave in ('filtro_divisional', 'filtro_sitio', 'filtro_modelo', 'filtro_equipo'):
        st.session_state[clave] = 'TODOS'
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

lista_sitios = ["TODOS"] + sorted(df_filtrado_sitios['SITIO_UNINET'].unique().tolist())
sitio_seleccionado = st.sidebar.selectbox("Selecciona Sitio Uninet:", lista_sitios, key="filtro_sitio")

if sitio_seleccionado != "TODOS":
    df_filtrado_equipos = df_filtrado_sitios[df_filtrado_sitios['SITIO_UNINET'] == sitio_seleccionado]
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
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "⚙️ Números de Parte de Hardware",
    "🔌 Capacidad y Estado de Puertos",
    "🌐 Interfaces",
    "📍 Ubicación de equipos",
    "🔄 Conciliación (SIRU vs Red)",
    "👥 Sesiones Infinitum"
])


# Aplicación de los filtros estándar y del buscador global en cascada a los Dataframes de vista
def filtrar_dataframe(df_target, campo_div='DIVISIONAL', campo_sit='SITIO_UNINET', campo_eq='NOMBRE_EQUIPO'):
    df_res = df_target.copy()
    if divisional_seleccionada != "TODOS" and campo_div in df_res.columns:
        df_res = df_res[df_res[campo_div] == divisional_seleccionada]
    if sitio_seleccionado != "TODOS" and campo_sit in df_res.columns:
        df_res = df_res[df_res[campo_sit] == sitio_seleccionado]
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
        width="stretch",
        hide_index=True,
    )


# Dataframe dinámico para descargas unificadas en Sidebar
df_para_descargar = pd.DataFrame()

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
    st.dataframe(df_tab1[cols_t1], use_container_width=True, hide_index=True)

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

# --- PESTAÑA 2: CAPACIDAD ---
with tab2:
    st.subheader("Análisis de Disponibilidad y Saturación de Puertos")
    df_tab2 = filtrar_dataframe(resumen_puertos_equipo)
    p_ocupados = df_tab2["Puertos_Ocupados"].sum()
    p_libres = df_tab2["Puertos_Libres"].sum()
    p_reservados = df_tab2["Puertos_Reservados"].sum()

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
            ].merge(df_tab2[claves_capacidad], on=claves_capacidad, how='inner', validate='many_to_one')
            mostrar_detalle_puertos(detalle, estado)

    st.markdown("---")
    st.markdown("Detalle de Capacidad por Chasis")
    st.dataframe(
        df_tab2[
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
        use_container_width=True,
        hide_index=True,
    )

# --- PESTAÑA 3: CAPA INTERFACES L1 ---
with tab3:
    st.subheader("Auditoría de Enlaces e Interfaces L1")
    if df_interfaces.empty:
        st.info("ℹ️ No hay datos disponibles para Interfaces L1.")
    else:
        # Relacionar L1 mediante los Slots activos obtenidos de la selección SIRU
        df_siru_f = filtrar_dataframe(df_siru)
        slots_activos = df_siru_f["SLOT"].unique().tolist()
        df_tab3 = df_interfaces[df_interfaces["SLOT"].isin(slots_activos)].copy()

        if buscar_ip_vlan:
            df_tab3 = df_tab3[
                (
                    df_tab3["IP_ADDRESS"].str.contains(
                        buscar_ip_vlan, case=False
                    )
                )
                | (df_tab3["VLAN"].str.contains(buscar_ip_vlan, case=False))
            ]

        c1, c2, c3 = st.columns(3)
        c1.metric(
            "🟢 Interfaces Activas (Up)",
            f"{len(df_tab3[df_tab3['SHUTDOWN'] == 0]):,}",
        )
        c2.metric(
            "🛑 En Shutdown (Administrativo)",
            f"{len(df_tab3[df_tab3['SHUTDOWN'] == 1]):,}",
        )
        c3.metric("🔑 VLANs Únicas en Uso", f"{df_tab3['VLAN'].nunique():,}")

        st.markdown("---")
        st.dataframe(
            df_tab3[
                [
                    "SLOT",
                    "STATUS_L1",
                    "SHUTDOWN",
                    "IP_ADDRESS",
                    "ANCHO_BANDA",
                    "PROTOCOLO",
                    "VLAN",
                    "TRUNK",
                    "DESC_L1",
                ]
            ],
            column_config={
                "SHUTDOWN": st.column_config.CheckboxColumn("Shutdown")
            },
            use_container_width=True,
            hide_index=True,
        )

# --- PESTAÑA 4: INFRAESTRUCTURA Y LOCALIZACIÓN ---
with tab4:
    st.subheader("📍 Localización en sitio")
    df_tab4 = filtrar_dataframe(df_ubicacion_equipos)
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
    st.dataframe(df_tab4[cols_t4], use_container_width=True, hide_index=True)

# --- PESTAÑA 5: CONCILIACIÓN DE TABLAS (CRUCE DIRECTO) ---
with tab5:
    st.subheader("🔄 Diagnóstico Cruzado de Integridad Operativa")
    st.markdown(
        "Análisis automático cruzando las asignaciones lógicas de "
        "SIRU_DSL y estados de capa física de INTERFACE_L1 indexados por Slot."
    )
    df_tab5 = filtrar_dataframe(df_conciliacion_maestra)

    # Vinculamos esta vista al botón global de descarga
    df_para_descargar = df_tab5.copy()

    alertas_totales = len(
        df_tab5[df_tab5["Discrepancia"] != "✅ Operación Alineada"]
    )
    promedio_trafico = (
        df_tab5["TRAFICO_95"].astype(float).mean()
        if "TRAFICO_95" in df_tab5.columns
        else 0
    )

    k_c1, k_c2, k_c3 = st.columns(3)
    k_c1.metric(
        "🚨 Discrepancias Detectadas",
        f"{alertas_totales}",
        delta="- Estable" if alertas_totales == 0 else "Acción Requerida",
    )
    k_c2.metric(
        "📈 Tráfico Promedio (95th Percentile)",
        f"{promedio_trafico:.2f} Mbps"
        if pd.notna(promedio_trafico)
        else "0.00 Mbps",
    )
    k_c3.metric(
        "🔗 Enlaces con Métrica OK",
        f"{len(df_tab5[df_tab5['OK_MET'] == 'SI'])} de {len(df_tab5)}",
    )

    st.markdown("---")
    cols_cruzadas = [
        "NOMBRE_EQUIPO",
        "SLOT",
        "Discrepancia",
        "Puertos_Asignados",
        "Puertos_Libres_Siru",
        "STATUS_L1",
        "SHUTDOWN",
        "IP_ADDRESS",
        "ANCHO_BANDA",
        "TRAFICO_95",
    ]
    st.dataframe(
        df_tab5[cols_cruzadas],
        column_config={
            "Discrepancia": st.column_config.TextColumn(
                "Análisis de Consistencia", width="large"
            ),
            "SHUTDOWN": st.column_config.CheckboxColumn("Shutdown"),
            "TRAFICO_95": st.column_config.NumberColumn("Tráfico (Mbps)"),
        },
        use_container_width=True,
        hide_index=True,
    )

with tab6:
    equipos_sesiones = filtrar_dataframe(df_siru)[[
        'NOMBRE_EQUIPO',
        'MODELO_EQUIPO',
        'SLOT',
        'PUERTO',
        'NUM_PARTE_SUBTARJETA',
    ]].drop_duplicates()
    mostrar_sesiones(equipos_sesiones)


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
