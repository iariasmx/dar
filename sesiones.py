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
    # 1. Construimos la URL de conexión a partir de tu db_config
    url_conexion = (
        f"mysql+mysqlconnector://{db_config['user']}:{db_config['password']}"
        f"@{db_config['host']}:{db_config.get('port', 3306)}/{db_config['database']}"
    )

    try:
        # 2. Creamos el motor compatible con Pandas
        engine = create_engine(url_conexion)

        # 3. Ejecutamos pasándole el 'engine' en lugar de 'conexion'
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
        # Añadido por seguridad para capturar errores de base de datos
        import streamlit as st
        st.error(f"❌ Error al cargar sesiones desde MySQL: {e}")
        return pd.DataFrame()


def preparar_sesiones(datos):
    datos = datos.copy()
    for campo in ('HOSTNAME', 'TIPO', 'SLOT'):
        datos[campo] = datos[campo].fillna('').astype(str).str.strip()
    datos['SLOT'] = datos['SLOT'].str.lstrip("'")
    datos = datos[datos['SLOT'].ne('') & ~datos['SLOT'].str.contains('.', regex=False)].copy()
    texto = datos['MAX_USER_SESSION'].fillna('').astype(str).str.strip()
    # No convertir valores inválidos a cero: se reportan como datos pendientes.
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
        datos = datos[datos['TIPO'] == tipo]

    invalidos = datos['SESIONES'].isna().sum()
    if invalidos:
        st.warning(f'{invalidos:,} registros tienen MAX_USER_SESSION vacío o inválido y no se suman.')

    if datos.duplicated(['HOSTNAME', 'TIPO', 'SLOT'], keep=False).any():
        st.warning('Hay interfaces repetidas por hostname, tipo y slot. Se suman todas sus filas; revisar la carga de origen.')

    validos = datos.dropna(subset=['SESIONES'])

    c1, c2, c3 = st.columns(3)
    c1.metric(
        'Total de sesiones por equipo',
        f"{int(validos['SESIONES'].sum()):,}" if not validos.empty else 'Sin datos válidos',
    )
    c2.metric('Equipos', f"{datos.loc[datos['HOSTNAME'].ne(''), 'HOSTNAME'].nunique():,}")
    c3.metric('Interfaces', f"{len(datos.drop_duplicates(['HOSTNAME', 'TIPO', 'SLOT'])):,}")

    detalle = datos[['HOSTNAME', 'HOSTNAME_CORTO', 'MODELO_EQUIPO', 'TIPO', 'SLOT', 'SESIONES']].copy()
    # detalle['MODELO_NORMALIZADO'] = detalle['MODELO_EQUIPO'].apply(normalizar_modelo)

    resumen_caja = detalle.groupby(
        ['HOSTNAME', 'MODELO_EQUIPO'],
        dropna=False,
    )['SESIONES'].sum(min_count=1).reset_index()

    reglas_caja = resumen_caja['MODELO_EQUIPO'].apply(regla_caja_por_modelo)

    resumen_caja['CAPACIDAD_CAJA'] = reglas_caja.apply(lambda regla: regla['capacidad']).astype(int)
    resumen_caja['UMBRAL_CAJA_75'] = reglas_caja.apply(lambda regla: regla['umbral_75']).astype(int)
    # resumen_caja['LEYENDA_UMBRAL_CAJA'] = reglas_caja.apply(lambda regla: regla['leyenda'])

    resumen_caja['%_USO_CAJA'] = (
        resumen_caja['SESIONES'] / resumen_caja['CAPACIDAD_CAJA'] * 100
    ).round(1)

    resumen_caja['SEMAFORO_CAJA'] = resumen_caja.apply(
        lambda fila: calcular_semaforo(fila['SESIONES'], fila['CAPACIDAD_CAJA']),
        axis=1,
    )

    resumen_slot = detalle.groupby(
        ['HOSTNAME', 'MODELO_EQUIPO', 'TIPO', 'SLOT'],
        dropna=False,
    )['SESIONES'].sum(min_count=1).reset_index()

    reglas_slot = resumen_slot['MODELO_EQUIPO'].apply(regla_slot_por_modelo)

    resumen_slot['CAPACIDAD_SLOT'] = reglas_slot.apply(lambda regla: regla['capacidad']).astype(int)
    resumen_slot['UMBRAL_SLOT_75'] = reglas_slot.apply(lambda regla: regla['umbral_75']).astype(int)
    # resumen_slot['LEYENDA_UMBRAL_SLOT'] = reglas_slot.apply(lambda regla: regla['leyenda'])

    resumen_slot['%_USO_SLOT'] = (
        resumen_slot['SESIONES'] / resumen_slot['CAPACIDAD_SLOT'] * 100
    ).round(1)

    resumen_slot['SEMAFORO_SLOT'] = resumen_slot.apply(
        lambda fila: calcular_semaforo(fila['SESIONES'], fila['CAPACIDAD_SLOT']),
        axis=1,
    )

    st.markdown('**Semáforo por caja**')
    st.dataframe(
        resumen_caja,
        hide_index=True,
        width='stretch',
        column_config={
            'SESIONES': st.column_config.NumberColumn('Sesiones por equipo', format='%d'),
            'CAPACIDAD_CAJA': st.column_config.NumberColumn('Capacidad caja', format='%d'),
            'UMBRAL_CAJA_75': st.column_config.NumberColumn('Umbral caja 75%', format='%d'),
            # 'LEYENDA_UMBRAL_CAJA': st.column_config.TextColumn('Regla aplicada a caja'),
            '%_USO_CAJA': st.column_config.ProgressColumn(
                'Uso caja',
                format='%.1f%%',
                min_value=0.0,
                max_value=100.0,
            ),
            'SEMAFORO_CAJA': st.column_config.TextColumn('Semáforo caja'),
        },
    )

    st.markdown('**Semáforo por slot**')
    st.dataframe(
        resumen_slot,
        hide_index=True,
        width='stretch',
        column_config={
            'SESIONES': st.column_config.NumberColumn('Sesiones por slot', format='%d'),
            'CAPACIDAD_SLOT': st.column_config.NumberColumn('Capacidad slot', format='%d'),
            'UMBRAL_SLOT_75': st.column_config.NumberColumn('Umbral slot 75%', format='%d'),
            # 'LEYENDA_UMBRAL_SLOT': st.column_config.TextColumn('Regla aplicada al slot'),
            '%_USO_SLOT': st.column_config.ProgressColumn(
                'Uso slot',
                format='%.1f%%',
                min_value=0.0,
                max_value=100.0,
            ),
            'SEMAFORO_SLOT': st.column_config.TextColumn('Semáforo slot'),
        },
    )

    with st.expander('Ver detalle por interfaz'):
        st.dataframe(
            detalle,
            hide_index=True,
            width='stretch',
            column_config={
                'SESIONES': st.column_config.NumberColumn('Sesiones totales', format='%d'),
            },
        )

    col_descarga1, col_descarga2 = st.columns(2)

    with col_descarga1:
        st.download_button(
            'Descargar sesiones por caja',
            resumen_caja.to_csv(index=False).encode('utf-8'),
            file_name='sesiones_infinitum_por_caja.csv',
            mime='text/csv',
            key='descargar_sesiones_caja',
        )

    with col_descarga2:
        st.download_button(
            'Descargar sesiones por slot',
            resumen_slot.to_csv(index=False).encode('utf-8'),
            file_name='sesiones_infinitum_por_slot.csv',
            mime='text/csv',
            key='descargar_sesiones_slot',
        )