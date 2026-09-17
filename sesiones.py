"""Consulta y visualización de sesiones Infinitum por interfaz física."""

import mysql.connector
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine

from config import db_config

def normalizar_modelo(modelo):
    return str(modelo or '').upper().replace('-', '').replace('_', '').replace(' ', '')

def regla_caja_por_modelo(modelo):
    modelo = normalizar_modelo(modelo)

    if any(valor in modelo for valor in ('9010', '480', '960')):
        capacidad = 128000
        familia = 'Caja 9010/480/960'
    elif any(valor in modelo for valor in ('204', '304')):
        capacidad = 32000
        familia = 'Caja 204/304'
    elif '10004' in modelo:
        capacidad = 64000
        familia = 'Caja 10004'
    else:
        capacidad = 32000
        familia = 'Caja default'

    umbral_75 = int(capacidad * 0.75)

    return {
        'capacidad': int(capacidad),
        'umbral_75': umbral_75,
        'leyenda': f'{familia}: {capacidad:,} × 75% = {umbral_75:,}',
    }


def regla_slot_por_modelo(modelo):
    modelo = normalizar_modelo(modelo)

    if any(valor in modelo for valor in ('9010', '480', '960')):
        capacidad = 64000
        familia = 'Slot 9010/480/960'
    elif any(valor in modelo for valor in ('204', '304')):
        capacidad = 32000
        familia = 'Slot 204/304'
    elif '10004' in modelo:
        capacidad = 48000
        familia = 'Slot 10004'
    else:
        capacidad = 32000
        familia = 'Slot default'

    umbral_75 = int(capacidad * 0.75)

    return {
        'capacidad': int(capacidad),
        'umbral_75': umbral_75,
        'leyenda': f'{familia}: {capacidad:,} × 75% = {umbral_75:,}',
    }


def capacidad_caja_por_modelo(modelo):
    return regla_caja_por_modelo(modelo)['capacidad']


def capacidad_slot_por_modelo(modelo):
    return regla_slot_por_modelo(modelo)['capacidad']


def calcular_semaforo(sesiones, capacidad):
    if pd.isna(sesiones):
        return '⚪ Sin dato'

    capacidad = pd.to_numeric(capacidad, errors='coerce')
    if pd.isna(capacidad) or capacidad <= 0:
        return '⚪ Sin capacidad'

    umbral_75 = capacidad * 0.75
    umbral_90 = capacidad * 0.90

    if sesiones <= umbral_75:
        return '🟢 OK'

    if sesiones <= umbral_90:
        return '🟡 Atención'

    return '🔴 Saturado'




def evaluar_semaforo_caja(modelo, sesiones):
    return calcular_semaforo(sesiones, capacidad_caja_por_modelo(modelo))


def evaluar_semaforo_slot(modelo, sesiones):
    return calcular_semaforo(sesiones, capacidad_slot_por_modelo(modelo))


@st.cache_data(ttl=300, show_spinner='Consultando sesiones Infinitum…')
def cargar_sesiones():
    url_conexion = (
        f"mysql+mysqlconnector://{db_config['user']}:{db_config['password']}"
        f"@{db_config['host']}:{db_config.get('port', 3306)}/{db_config['database']}"
    )

    try:
        engine = create_engine(url_conexion)
        # REGLA OBLIGATORIA: Filtrar desde MySQL para omitir sub-interfaces lógicas con punto
        return pd.read_sql(
            """
            SELECT ID, HOSTNAME, TIPO, SLOT, MAX_USER_SESSION
            FROM INFINITUM_dslSessionSemanal
            WHERE SLOT IS NOT NULL
              AND TRIM(SLOT) != ''
              AND SLOT NOT LIKE '%.%'
            """,
            engine,
        )
    except Exception as e:
        import streamlit as st
        st.error(f"❌ Error al cargar sesiones desde MySQL: {e}")
        return pd.DataFrame()


def preparar_sesiones(datos):
    datos = datos.copy()
    for campo in ('HOSTNAME', 'TIPO', 'SLOT'):
        datos[campo] = datos[campo].fillna('').astype(str).str.strip()
    datos['SLOT'] = datos['SLOT'].str.lstrip("'")

    # REGLA OBLIGATORIA: Doble validación en Pandas para descartar cualquier fila con punto '.'
    datos = datos[datos['SLOT'].ne('') & ~datos['SLOT'].str.contains('.', regex=False)].copy()

    texto = datos['MAX_USER_SESSION'].fillna('').astype(str).str.strip()
    datos['SESIONES'] = pd.to_numeric(texto.where(texto.str.fullmatch(r'[0-9]+')), errors='coerce')
    return datos


def preparar_sesiones(datos):
    datos = datos.copy()
    for campo in ('HOSTNAME', 'TIPO', 'SLOT'):
        datos[campo] = datos[campo].fillna('').astype(str).str.strip()
    datos['SLOT'] = datos['SLOT'].str.lstrip("'")

    # MODIFICACIÓN: Ya no eliminamos las filas con punto '.' aquí
    datos = datos[datos['SLOT'].ne('')].copy()

    texto = datos['MAX_USER_SESSION'].fillna('').astype(str).str.strip()
    datos['SESIONES'] = pd.to_numeric(texto.where(texto.str.fullmatch(r'[0-9]+')), errors='coerce')
    return datos

def filtrar_sesiones_por_equipos(datos, equipos):
    """Relaciona nombres cortos de SIRU con hostnames que incluyen dominio."""
    nombres = {
        str(equipo).strip().casefold().split('.', 1)[0]
        for equipo in equipos if pd.notna(equipo)
    }
    nombres.discard('')
    nombres_sesiones = datos['HOSTNAME'].fillna('').str.strip().str.casefold().str.split('.', n=1).str[0]
    return datos[nombres_sesiones.isin(nombres)].copy()


def agregar_modelo_equipo(datos, equipos):
    """Agrega el modelo de SIRU a sesiones cruzando por hostname corto."""
    if not isinstance(equipos, pd.DataFrame) or equipos.empty:
        datos = datos.copy()
        datos['MODELO_EQUIPO'] = ''
        datos['HOSTNAME_CORTO'] = (
            datos['HOSTNAME']
            .fillna('')
            .astype(str)
            .str.strip()
            .str.casefold()
            .str.split('.', n=1)
            .str[0]
        )
        return datos

    catalogo = equipos[['NOMBRE_EQUIPO', 'MODELO_EQUIPO']].copy()
    catalogo['NOMBRE_EQUIPO'] = catalogo['NOMBRE_EQUIPO'].fillna('').astype(str).str.strip()
    catalogo['MODELO_EQUIPO'] = catalogo['MODELO_EQUIPO'].fillna('').astype(str).str.strip()

    catalogo['EQUIPO_CORTO'] = (
        catalogo['NOMBRE_EQUIPO']
        .str.casefold()
        .str.split('.', n=1)
        .str[0]
    )

    catalogo = catalogo[
        catalogo['EQUIPO_CORTO'].ne('')
        & catalogo['MODELO_EQUIPO'].ne('')
    ].drop_duplicates(subset=['EQUIPO_CORTO'], keep='first')

    datos = datos.copy()
    datos['HOSTNAME_CORTO'] = (
        datos['HOSTNAME']
        .fillna('')
        .astype(str)
        .str.strip()
        .str.casefold()
        .str.split('.', n=1)
        .str[0]
    )

    datos = datos.merge(
        catalogo[['EQUIPO_CORTO', 'MODELO_EQUIPO']],
        left_on='HOSTNAME_CORTO',
        right_on='EQUIPO_CORTO',
        how='left',
        validate='many_to_one',
    )

    datos['MODELO_EQUIPO'] = datos['MODELO_EQUIPO'].fillna('').astype(str).str.strip()
    return datos.drop(columns=['EQUIPO_CORTO'])


@st.fragment
def mostrar_sesiones(equipos):
    st.subheader('Sesiones Infinitum')
    st.caption('La información se obtiene del archivo \'dsl_session_semanal\'.')

    if st.button('Actualizar sesiones', key='actualizar_sesiones'):
        cargar_sesiones.clear()

    try:
        # 1. Cargar y preparar datos (excluyendo sub-interfaces con punto)
        datos = preparar_sesiones(cargar_sesiones())

        if isinstance(equipos, pd.DataFrame):
            nombres_equipos = equipos['NOMBRE_EQUIPO'].dropna().unique().tolist()
            datos = filtrar_sesiones_por_equipos(datos, nombres_equipos)
            datos = agregar_modelo_equipo(datos, equipos)
        else:
            datos = filtrar_sesiones_por_equipos(datos, equipos)
            datos['MODELO_EQUIPO'] = ''

    except Exception as error:
        st.error(f'No se pudieron consultar las sesiones Infinitum: {error}')
        return

    if datos.empty:
        st.info('No hay sesiones de interfaces sin punto en SLOT para los equipos seleccionados en SIRU.')
        return

    tipos_disponibles = [None] + sorted(datos['TIPO'].unique().tolist())
    if st.session_state.get('sesiones_tipo') not in tipos_disponibles:
        st.session_state['sesiones_tipo'] = None

    tipo = st.selectbox(
        'Tipo de interfaz',
        tipos_disponibles,
        format_func=lambda valor: 'Todos los tipos' if valor is None else (valor or 'Sin tipo'),
        key='sesiones_tipo',
    )

    if tipo is not None:
        datos = datos[datos['TIPO'] == tipo].copy()

    if datos.empty:
        st.info('No hay sesiones para el tipo de interfaz seleccionado.')
        return

    # --- 1. EXTRACCIÓN INMEDIATA Y SEGURA DE SLOT Y SUBSLOT ---
    def extraer_identificadores(row):
        slot_completo = str(row['SLOT']).strip().lstrip("'")
        modelo = str(row['MODELO_EQUIPO']).upper()

        # Quitar sub-interfaces lógicas si existen
        slot_sin_subinterfaz = slot_completo.split('.')[0]
        partes = slot_sin_subinterfaz.split('/')

        import re

        slot_principal = 0
        subslot = "0"

        # Regla Cisco ASR / NAUCALPAN (rack/slot/module/port)
        if any(x in modelo for x in ('CISCO', 'ASR', '9010', '480', '960')) or 'NAUCALPAN' in str(
                row['HOSTNAME']).upper():
            # Extraer Slot (Índice 1)
            if len(partes) >= 2:
                match_slot = re.search(r'\d+', partes[1])
                if match_slot:
                    slot_principal = int(match_slot.group(0))

            # Extraer Subslot combinando modulo/tarjeta (ej. de '0/0/1/2' extrae '0/1')
            if len(partes) >= 4:
                m_mod = re.search(r'\d+', partes[1])
                m_sub = re.search(r'\d+', partes[2])
                mod_val = m_mod.group(0) if m_mod else "0"
                sub_val = m_sub.group(0) if m_sub else "0"
                subslot = f"{mod_val}/{sub_val}"
            elif len(partes) == 3:
                m_mod = re.search(r'\d+', partes[1])
                subslot = m_mod.group(0) if m_mod else "0"

        # Regla Juniper / Default (slot/subslot/port)
        else:
            # Extraer Slot (Índice 0)
            if partes and len(partes) > 0:
                match_slot = re.search(r'\d+', partes[0])
                if match_slot:
                    slot_principal = int(match_slot.group(0))

            # Extraer Subslot (Índice 1)
            if len(partes) >= 2:
                match_sub = re.search(r'\d+', partes[1])
                if match_sub:
                    subslot = match_sub.group(0)

        return pd.Series([slot_principal, subslot])

    # Aplicamos la extracción al dataframe original
    datos[['SLOT_PRINCIPAL', 'SUBSLOT']] = datos.apply(extraer_identificadores, axis=1)

    # --- 2. CREACIÓN DE PESTAÑAS (TABS) PARA CADA VISTA ---
    tab_slot, tab_subslot = st.tabs(['Visualización por Slot', 'Visualización por Subslot'])

    # ==================== VISTA 1: POR SLOT ====================
    with tab_slot:
        datos_agrupados_slot = datos.groupby(
            ['HOSTNAME', 'MODELO_EQUIPO', 'TIPO', 'SLOT_PRINCIPAL'],
            as_index=False
        ).agg({'SESIONES': 'sum'})

        datos_agrupados_slot = datos_agrupados_slot.rename(columns={'SLOT_PRINCIPAL': 'SLOT'})
        datos_agrupados_slot = datos_agrupados_slot.sort_values(by=['HOSTNAME', 'SLOT', 'TIPO'],
                                                                ascending=[True, True, True])

        datos_agrupados_slot['CAPACIDAD_SLOT'] = datos_agrupados_slot['MODELO_EQUIPO'].apply(capacidad_slot_por_modelo)
        datos_agrupados_slot['UMBRAL_75'] = datos_agrupados_slot['MODELO_EQUIPO'].apply(
            lambda mod: regla_slot_por_modelo(mod)['umbral_75'])
        datos_agrupados_slot['USO_SLOT_PCT'] = (
                    datos_agrupados_slot['SESIONES'] / datos_agrupados_slot['CAPACIDAD_SLOT'] * 100).fillna(0)
        datos_agrupados_slot['USO_SLOT_PCT_VISUAL'] = datos_agrupados_slot['USO_SLOT_PCT'].clip(upper=100.0)
        datos_agrupados_slot['SEMÁFORO_SLOT'] = datos_agrupados_slot.apply(
            lambda r: evaluar_semaforo_slot(r['MODELO_EQUIPO'], r['SESIONES']), axis=1)

        # Métricas de Slot
        v_slot = datos_agrupados_slot.dropna(subset=['SESIONES'])
        t_sesiones_slot = int(v_slot['SESIONES'].sum()) if not v_slot.empty else 0
        t_slots_físicos = len(datos_agrupados_slot['SLOT'].unique())

        c1, c2, c3 = st.columns(3)
        c1.metric("Total Slots Físicos", f"{t_slots_físicos:,}")
        c2.metric("Total Sesiones", f"{t_sesiones_slot:,}")
        sat_slot = (datos_agrupados_slot['SEMÁFORO_SLOT'] == '🔴 Saturado').sum()
        pct_sat_slot = (sat_slot / len(datos_agrupados_slot) * 100) if len(datos_agrupados_slot) > 0 else 0
        c3.metric("Líneas Saturadas (🔴)", f"{pct_sat_slot:.1f}%")

        st.write("### Semáforo por slot")
        st.dataframe(
            datos_agrupados_slot[
                ['HOSTNAME', 'MODELO_EQUIPO', 'TIPO', 'SLOT', 'SESIONES', 'CAPACIDAD_SLOT', 'UMBRAL_75',
                 'USO_SLOT_PCT_VISUAL', 'SEMÁFORO_SLOT']],
            column_config={
                "SLOT": st.column_config.NumberColumn("SLOT", format="%d"),
                "SESIONES": st.column_config.NumberColumn("Sesiones por tipo/slot", format="%d"),
                "USO_SLOT_PCT_VISUAL": st.column_config.ProgressColumn("Uso slot", format="%.1f%%", min_value=0,
                                                                       max_value=100),
            },
            use_container_width=True, hide_index=True
        )

        # ==================== VISTA 2: POR SUBSLOT ====================
        with tab_subslot:
            # Agrupamos incluyendo la columna 'SUBSLOT'
            datos_agrupados_sub = datos.groupby(
                ['HOSTNAME', 'MODELO_EQUIPO', 'TIPO', 'SLOT_PRINCIPAL', 'SUBSLOT'],
                as_index=False
            ).agg({'SESIONES': 'sum'})

            datos_agrupados_sub = datos_agrupados_sub.rename(columns={'SLOT_PRINCIPAL': 'SLOT'})
            datos_agrupados_sub = datos_agrupados_sub.sort_values(by=['HOSTNAME', 'SLOT', 'SUBSLOT', 'TIPO'],
                                                                  ascending=[True, True, True, True])

            # --- REGLA SOLICITADA: UMBRALES Y CAPACIDAD FIJOS DE 32,000 PARA SUBSLOT ---
            datos_agrupados_sub['CAPACIDAD_SUBSLOT'] = 32000

            # El umbral al 75% de 32,000 es exactamente 24,000
            datos_agrupados_sub['UMBRAL_75'] = int(32000 * 0.75)

            # Calcular el porcentaje de uso real sobre los 32,000
            datos_agrupados_sub['USO_SUBSLOT_PCT'] = (
                        datos_agrupados_sub['SESIONES'] / datos_agrupados_sub['CAPACIDAD_SUBSLOT'] * 100).fillna(0)
            datos_agrupados_sub['USO_SUBSLOT_PCT_VISUAL'] = datos_agrupados_sub['USO_SUBSLOT_PCT'].clip(upper=100.0)

            # Evaluar el semáforo usando la capacidad fija de 32,000
            datos_agrupados_sub['SEMÁFORO_SUBSLOT'] = datos_agrupados_sub.apply(
                lambda r: calcular_semaforo(r['SESIONES'], 32000), axis=1
            )

            # Métricas de Subslot
            v_sub = datos_agrupados_sub.dropna(subset=['SESIONES'])
            t_sesiones_sub = int(v_sub['SESIONES'].sum()) if not v_sub.empty else 0
            t_subslots = len(datos_agrupados_sub.groupby(['SLOT', 'SUBSLOT']))

            cs1, cs2, cs3 = st.columns(3)
            cs1.metric("Total Subslots", f"{t_subslots:,}")
            cs2.metric("Total Sesiones", f"{t_sesiones_sub:,}")
            sat_sub = (datos_agrupados_sub['SEMÁFORO_SUBSLOT'] == '🔴 Saturado').sum()
            pct_sat_sub = (sat_sub / len(datos_agrupados_sub) * 100) if len(datos_agrupados_sub) > 0 else 0
            cs3.metric("Subslots Saturados (🔴)", f"{pct_sat_sub:.1f}%")

            st.write("### Semáforo por subslot")
            st.dataframe(
                datos_agrupados_sub[[
                    'HOSTNAME', 'MODELO_EQUIPO', 'TIPO', 'SLOT', 'SUBSLOT',
                    'SESIONES', 'CAPACIDAD_SUBSLOT', 'UMBRAL_75', 'USO_SUBSLOT_PCT_VISUAL', 'SEMÁFORO_SUBSLOT'
                ]],
                column_config={
                    "SLOT": st.column_config.NumberColumn("SLOT FÍSICO", format="%d"),
                    "SUBSLOT": st.column_config.TextColumn("SUBSLOT / MODULO"),
                    "SESIONES": st.column_config.NumberColumn("Sesiones por subslot", format="%d"),
                    "CAPACIDAD_SUBSLOT": st.column_config.NumberColumn("Capacidad subslot", format="%d"),
                    "UMBRAL_75": st.column_config.NumberColumn("Umbral 75%", format="%d"),
                    "USO_SUBSLOT_PCT_VISUAL": st.column_config.ProgressColumn(
                        "Uso subslot",
                        help="Porcentaje consumido del total del subslot (Base 32k)",
                        format="%.1f%%",
                        min_value=0,
                        max_value=100,
                    ),
                    "SEMÁFORO_SUBSLOT": "Semáforo subslot"
                },
                use_container_width=True,
                hide_index=True
            )








