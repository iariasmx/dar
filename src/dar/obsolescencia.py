"""Cruce del inventario SIRU con el catálogo de obsolescencia UniNet."""

from pathlib import Path
import re
import unicodedata

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MATRIZ_PATH = PROJECT_ROOT / "data" / "reference" / "matriz_elementos_homologados_uninet.xlsx"

CATALOGO_COLUMNS = [
    "CLAVE_PARTE",
    "PROVEEDOR_MATRIZ",
    "MODELO_MATRIZ",
    "TIPO_PIEZA_MATRIZ",
    "DESCRIPCION_MATRIZ",
    "REEMPLAZO_SUGERIDO",
    "HOJA_MATRIZ",
]


def _normalizar(valor):
    """Normaliza títulos y valores para comparar nombres sin acentos ni formato."""
    if pd.isna(valor):
        return ""
    texto = unicodedata.normalize("NFKD", str(valor))
    texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
    return re.sub(r"\s+", " ", texto).strip().casefold()


def _normalizar_cabecera(valor):
    return re.sub(r"[^a-z0-9]+", " ", _normalizar(valor)).strip()


def _clave_parte(valor):
    """Compara números de parte sin distinguir mayúsculas ni espacios."""
    texto = _normalizar(valor).upper()
    if texto in {"", "NAN", "NONE", "#N/A", "N/A", "S/E", "N/D"}:
        return ""
    return re.sub(r"\s+", "", texto)


def _columna_por_nombre(columnas, candidatos):
    normalizadas = {_normalizar_cabecera(columna): columna for columna in columnas}
    for candidato in candidatos:
        if candidato in normalizadas:
            return normalizadas[candidato]
    return None


def _columna_por_tipo(columnas, tipo):
    """Resuelve el campo de pieza en hojas nuevas sin columna No. Parte."""
    tipo = _normalizar_cabecera(tipo)
    nombres = {_normalizar_cabecera(columna): columna for columna in columnas}

    if "transductor" in tipo:
        opciones = ["transductor"]
    elif "subtarjeta" in tipo:
        opciones = ["sub tarjeta de linea"]
    elif "tarjeta modular" in tipo:
        opciones = ["tarjeta modular"]
    elif "tarjeta de linea" in tipo:
        opciones = ["tarjeta de linea"]
    elif any(palabra in tipo for palabra in ("procesadora", "fabric", "memoria", "gestion")):
        opciones = ["procesadora fabric memoria etc"]
    elif any(palabra in tipo for palabra in ("fuente", "ventilador", "filtro", "accesorio", "cable")):
        opciones = ["fuente ventilador filtro accesorios etc"]
    elif "cvr" in tipo:
        opciones = ["cvr"]
    else:
        opciones = ["chasis"]

    for opcion in opciones:
        if opcion in nombres:
            return nombres[opcion]
    return None


def _unicos_texto(valores):
    unicos = []
    vistos = set()
    for valor in valores:
        if pd.isna(valor):
            continue
        texto = str(valor).strip()
        clave = _normalizar(texto)
        if clave in {"n/a", "n.a.", "s/e", "s/d", "#n/a", "nan"}:
            continue
        if texto and clave not in vistos:
            unicos.append(texto)
            vistos.add(clave)
    return " | ".join(unicos)


def cargar_catalogo_obsolescencia():
    """Recarga la matriz cuando cambia el archivo de referencia."""
    if not MATRIZ_PATH.exists():
        raise FileNotFoundError(f"No se encontró la matriz de homologación: {MATRIZ_PATH}")
    return _cargar_catalogo(str(MATRIZ_PATH), MATRIZ_PATH.stat().st_mtime_ns)


@st.cache_data(show_spinner="Leyendo matriz de obsolescencia...")
def _cargar_catalogo(ruta_matriz, modificado_ns):
    """Extrae partes marcadas explícitamente como obsoletas y su reemplazo."""
    hojas = pd.read_excel(
        ruta_matriz,
        sheet_name=None,
        header=2,
        engine="openpyxl",
    )
    registros = []

    for nombre_hoja, datos in hojas.items():
        columnas = list(datos.columns)
        proveedor_col = _columna_por_nombre(columnas, ["proveedor", "fabricante"])
        modelo_col = _columna_por_nombre(columnas, ["modelo", "model"])
        tipo_col = _columna_por_nombre(columnas, ["tipo", "tipo de elemento"])
        estatus_col = _columna_por_nombre(columnas, ["estatus", "status"])
        descripcion_col = next(
            (columna for columna in columnas if _normalizar_cabecera(columna).startswith("descripcion")),
            None,
        )
        reemplazo_col = next(
            (
                columna
                for columna in sorted(columnas, key=lambda c: "sugerido" not in _normalizar_cabecera(c))
                if "reemplazo" in _normalizar_cabecera(columna)
            ),
            None,
        )

        if not proveedor_col or not estatus_col:
            continue

        parte_cols = [
            columna
            for columna in columnas
            if (
                _normalizar_cabecera(columna) in {"no parte", "numero parte", "part number", "part no", "opn"}
                or "manufacturer part number" in _normalizar_cabecera(columna)
                or re.search(r"\bmpn\b", _normalizar_cabecera(columna))
            )
        ]

        for _, fila in datos.iterrows():
            estatus = str(fila.get(estatus_col, "")).strip()
            if "obsoleto" not in _normalizar(estatus):
                continue

            tipo = fila.get(tipo_col, "") if tipo_col else ""
            valores_parte = [fila.get(columna) for columna in parte_cols]
            if not any(_clave_parte(valor) for valor in valores_parte):
                parte_fallback = _columna_por_tipo(columnas, tipo)
                if parte_fallback:
                    valores_parte = [fila.get(parte_fallback)]

            claves = set()
            for valor in valores_parte:
                if pd.isna(valor):
                    continue
                # Algunas filas listan alternativas de número de parte en una misma celda.
                for alternativa in re.split(r"\s*(?:/|;|,|\n)\s*", str(valor)):
                    clave = _clave_parte(alternativa)
                    if clave:
                        claves.add(clave)

            for clave in claves:
                registros.append({
                    "CLAVE_PARTE": clave,
                    "PROVEEDOR_MATRIZ": fila.get(proveedor_col),
                    "MODELO_MATRIZ": fila.get(modelo_col) if modelo_col else "",
                    "TIPO_PIEZA_MATRIZ": tipo,
                    "DESCRIPCION_MATRIZ": fila.get(descripcion_col) if descripcion_col else "",
                    "REEMPLAZO_SUGERIDO": fila.get(reemplazo_col) if reemplazo_col else "",
                    "HOJA_MATRIZ": nombre_hoja,
                })

    if not registros:
        return pd.DataFrame(columns=CATALOGO_COLUMNS)
    return pd.DataFrame(registros, columns=CATALOGO_COLUMNS).drop_duplicates()


def detectar_piezas_obsoletas(inventario, catalogo):
    """Relaciona tarjetas y subtarjetas instaladas con partes obsoletas del catálogo."""
    if inventario.empty or catalogo.empty:
        return pd.DataFrame()

    columnas_equipo = [
        "DIVISIONAL", "SITIO_UNINET", "NOMBRE_EQUIPO", "MODELO_EQUIPO", "CHASIS", "SLOT"
    ]
    disponibles = [columna for columna in columnas_equipo if columna in inventario.columns]

    tarjetas = inventario[inventario["NUM_PARTE_TARJETA"].map(_clave_parte) != ""].drop_duplicates(
        subset=[columna for columna in ["NOMBRE_EQUIPO", "SLOT", "NUM_PARTE_TARJETA"] if columna in inventario.columns]
    )[disponibles + ["NUM_PARTE_TARJETA"]].copy()
    tarjetas.rename(columns={"NUM_PARTE_TARJETA": "NUM_PARTE_INSTALADA"}, inplace=True)
    tarjetas["SUBSLOT"] = ""
    tarjetas["TIPO_COMPONENTE"] = "Tarjeta"

    subtarjetas = inventario[inventario["NUM_PARTE_SUBTARJETA"].map(_clave_parte) != ""].drop_duplicates(
        subset=[
            columna for columna in
            ["NOMBRE_EQUIPO", "SLOT", "SUBSLOT", "NUM_PARTE_SUBTARJETA"]
            if columna in inventario.columns
        ]
    )[disponibles + ["SUBSLOT", "NUM_PARTE_SUBTARJETA"]].copy()
    subtarjetas.rename(columns={"NUM_PARTE_SUBTARJETA": "NUM_PARTE_INSTALADA"}, inplace=True)
    subtarjetas["TIPO_COMPONENTE"] = "Subtarjeta"

    chasises = inventario[inventario["CHASIS"].map(_clave_parte) != ""].drop_duplicates(
        subset=[columna for columna in ["NOMBRE_EQUIPO", "CHASIS"] if columna in inventario.columns]
    )[disponibles].copy()
    chasises["NUM_PARTE_INSTALADA"] = chasises["CHASIS"]
    chasises["SLOT"] = ""
    chasises["SUBSLOT"] = ""
    chasises["TIPO_COMPONENTE"] = "Chasis"

    piezas = pd.concat([chasises, tarjetas, subtarjetas], ignore_index=True, sort=False)
    piezas["CLAVE_PARTE"] = piezas["NUM_PARTE_INSTALADA"].map(_clave_parte)
    coincidencias = piezas.merge(catalogo, on="CLAVE_PARTE", how="inner")
    if coincidencias.empty:
        return coincidencias

    claves_fisicas = [
        columna for columna in [
            "DIVISIONAL", "SITIO_UNINET", "NOMBRE_EQUIPO", "MODELO_EQUIPO", "CHASIS",
            "SLOT", "SUBSLOT", "TIPO_COMPONENTE", "NUM_PARTE_INSTALADA",
        ] if columna in coincidencias.columns
    ]
    agregaciones = {
        columna: _unicos_texto
        for columna in [
            "PROVEEDOR_MATRIZ", "MODELO_MATRIZ", "TIPO_PIEZA_MATRIZ",
            "DESCRIPCION_MATRIZ", "REEMPLAZO_SUGERIDO", "HOJA_MATRIZ",
        ]
    }
    return coincidencias.groupby(claves_fisicas, dropna=False, as_index=False).agg(agregaciones)
