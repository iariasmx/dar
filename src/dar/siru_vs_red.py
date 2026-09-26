import pandas as pd
import streamlit as st


def generar_matriz_conectividad(df_siru, df_equipos, df_interfaces, divisional="TODOS", sitio="TODOS", modelo="TODOS",
                                equipo="TODOS"):
    st.subheader("🤝 Matriz de Conectividad e Integridad de Red (SIRU vs Red)")

    # 🚀 SOLUCIÓN: Ampliar el límite de celdas para el coloreado de Pandas Styler
    pd.set_option("styler.render.max_elements", 500000)

    if df_equipos.empty or df_interfaces.empty or df_siru.empty:
        st.error("❌ No se pueden cruzar los datos porque alguna de las tablas está vacía en MySQL.")
        return

    # 1. Normalización elástica de Nombres de Routers (Remover .mex, .mer, etc.)
    df_equipos_limpio = df_equipos.copy()
    df_equipos_limpio['HOST_CLEAN'] = df_equipos_limpio['HOSTNAME'].str.lower().str.strip().str.split('.').str[0]
    mapeo_ids = df_equipos_limpio.set_index('HOST_CLEAN')['ID_EQUIPO'].to_dict()

    df_siru_analisis = df_siru.copy()
    df_siru_analisis['HOST_CLEAN'] = df_siru_analisis['NOMBRE_EQUIPO'].str.lower().str.strip().str.split('.').str[0]
    df_siru_analisis['ID_EQUIPO_CRUCE'] = df_siru_analisis['HOST_CLEAN'].map(mapeo_ids)

    # 2. Estandarización de Interfaces
    def estandarizar_puerto(val):
        if pd.isna(val): return ""
        return str(val).strip().lower().replace("_", "/").replace("-", "/")

    df_siru_analisis['PUERTO_LIMPIO'] = df_siru_analisis['PUERTO_GENERADO'].apply(estandarizar_puerto)

    df_interfaces_analisis = df_interfaces.copy()
    df_interfaces_analisis['PUERTO_LIMPIO'] = df_interfaces_analisis['SLOT'].apply(estandarizar_puerto)

    # Tratamiento preventivo de nulos usando los nombres reales de tus tablas
    if 'DESCRIPCION' in df_siru_analisis.columns:
        df_siru_analisis['DESCRIPCION'] = df_siru_analisis['DESCRIPCION'].fillna("")
    if 'DESC_L1' in df_interfaces_analisis.columns:
        df_interfaces_analisis['DESC_L1'] = df_interfaces_analisis['DESC_L1'].fillna("")

    # 3. Realizar el Cruce Relacional con LEFT JOIN
    matriz = pd.merge(
        df_siru_analisis,
        df_interfaces_analisis,
        left_on=['ID_EQUIPO_CRUCE', 'PUERTO_LIMPIO'],
        right_on=['ID_EQUIPO', 'PUERTO_LIMPIO'],
        how='left',
        suffixes=('_SIRU', '_L1')
    )

    # 4. Motor de Diagnóstico con actualizaciones de reglas de negocio
    def evaluar_integridad(row):
        if pd.isna(row['ID_EQUIPO_CRUCE']):
            return 'Desconexión: Router de SIRU no mapeado en EQUIPOS_DSL'
        if pd.isna(row['ID_EQUIPO']):
            if row['PUERTO_LIMPIO'] == '0/0/0/0':
                return 'Puerto sin especificar (0/0/0/0)'
            return 'Desconexión: Puerto de SIRU no existe físicamente en el Router'

        status_siru = str(row['TIPO_ASIG']).upper()
        status_l1 = str(row['STATUS_L1']).upper()

        # REGLA DE NEGOCIO: Puerto marcado como LIBRE y físicamente DOWN es una situación correcta (OK)
        if 'LIBRE' in status_siru and 'DOWN' in status_l1:
            return 'OK: Puerto Libre y Desconectado'

        # 📝 REGLA MODIFICADA: Se cambia "Puerto Pirata" por "Inconsistencia"
        elif 'LIBRE' in status_siru and 'UP' in status_l1:
            return 'Riesgo: Inconsistencia (Tráfico en puerto marcado Libre)'

        elif 'BAJA' in status_siru and 'UP' in status_l1:
            return 'Riesgo: Servicio Activo en Puerto Dado de Baja'
        elif 'UP' in status_l1 and ('OCUPADO' in status_siru or status_siru not in ['LIBRE', 'RESERVADO']):
            return 'OK: Concordancia Total (Inventariado y Operando)'
        elif 'ADMIN-DOWN' in status_l1 and 'LIBRE' in status_siru:
            return 'OK: Puerto Disponible (Apagado y Libre)'
        elif 'ADMIN-DOWN' in status_l1 and ('OCUPADO' in status_siru or status_siru not in ['LIBRE', 'RESERVADO']):
            return 'Advertencia: Puerto Desperdiciado (Asignado pero Apagado)'
        elif 'DOWN' in status_l1:
            return 'Falla: Alerta Física (Puerto Asignado Caído)'
        else:
            return 'Revisión: Diferencia de Criterio'

    matriz['DIAGNOSTICO'] = matriz.apply(evaluar_integridad, axis=1)

    # =====================================================================
    # ⚡ INYECCIÓN DE FILTROS EN CASCADA PROCEDENTES DE app.py
    # =====================================================================
    if divisional != "TODOS":
        matriz = matriz[matriz['DIVISIONAL'] == divisional]

    if sitio != "TODOS":
        matriz = matriz[matriz['SITIO_UNINET'] == sitio]

    if modelo != "TODOS":
        matriz = matriz[matriz['MODELO_EQUIPO'] == modelo]

    if equipo != "TODOS":
        matriz = matriz[matriz['NOMBRE_EQUIPO'] == equipo]
    # =====================================================================

    # 5. Visualización de Métricas del Estado del Inventario (Calculadas POST-FILTRO)
    totales = matriz['DIAGNOSTICO'].value_counts()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Registros Evaluados", f"{len(matriz):,}")

    # Métrica de puertos comodín
    c2.metric(
        "Puertos sin especificar (0/0/0/0)",
        f"{totales.get('Puerto sin especificar (0/0/0/0)', 0)}",
        delta_color="inverse"
    )

    # Contador global de concordancias
    concordancias_ok = (
            totales.get('OK: Concordancia Total (Inventariado y Operando)', 0) +
            totales.get('OK: Puerto Disponible (Apagado y Libre)', 0) +
            totales.get('OK: Puerto Libre y Desconectado', 0)
    )
    c3.metric("Concordancias Exitosas (OK)", f"{concordancias_ok:,}")

    # 6. Filtros e Interfaz Gráfica Interna de la Matriz
    filtro_diag = st.multiselect(
        "Filtrar Registros por Diagnóstico Operativo:",
        options=matriz['DIAGNOSTICO'].unique(),
        default=matriz['DIAGNOSTICO'].unique()
    )

    # Forzar la existencia segura de las columnas para evitar excepciones visuales
    if 'DESCRIPCION' not in matriz.columns:
        matriz['DESCRIPCION'] = "No disponible"
    if 'DESC_L1' not in matriz.columns:
        matriz['DESC_L1'] = "No disponible"
    if 'TIPO_ASIG' not in matriz.columns:
        matriz['TIPO_ASIG'] = "No asignado"

    # Estructuración final de las columnas a renderizar
    columnas_mostrar = [
        'NOMBRE_EQUIPO', 'PUERTO_GENERADO', 'TIPO_ASIG', 'DESCRIPCION',
        'SLOT_L1', 'DESC_L1', 'STATUS_L1', 'DIAGNOSTICO'
    ]

    df_mostrar = matriz[matriz['DIAGNOSTICO'].isin(filtro_diag)][columnas_mostrar].rename(
        columns={
            'SLOT_L1': 'PUERTO_REAL_L1',
            'DESCRIPCION': 'DESCRIPCION_SIRU'
        }
    )

    def color_diagnostico(val):
        if 'OK' in val:
            return 'background-color: rgba(40, 167, 69, 0.12); color: #1e4620; font-weight: bold;'
        elif 'Falla' in val:
            return 'background-color: rgba(220, 53, 69, 0.12); color: #721c24; font-weight: bold;'
        elif 'Riesgo' in val:
            return 'background-color: rgba(253, 126, 20, 0.12); color: #856404; font-weight: bold;'
        elif 'especificar' in val:
            return 'background-color: rgba(255, 193, 7, 0.15); color: #6c757d;'
        return 'background-color: rgba(108, 117, 125, 0.1); color: #495057;'

    st.dataframe(
        df_mostrar.style.map(color_diagnostico, subset=['DIAGNOSTICO']),
        use_container_width=True,
        hide_index=True,
        column_config={
            "NOMBRE_EQUIPO": "Equipo (SIRU)",
            "PUERTO_GENERADO": "Puerto (SIRU)",
            "TIPO_ASIG": "Tipo Asignación (SIRU)",
            "DESCRIPCION_SIRU": "Descripción (SIRU)",
            "PUERTO_REAL_L1": "Puerto Real (Router)",
            "DESC_L1": "Descripción Física (L1)",
            "STATUS_L1": "Estatus Físico",
            "DIAGNOSTICO": "Dictamen de Integridad de Datos"
        }
    )
