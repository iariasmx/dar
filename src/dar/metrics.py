"""Funciones de cálculo independientes de la interfaz de Streamlit."""


def porcentaje(parte, total):
    """Devuelve un porcentaje seguro para indicadores de capacidad."""
    return 0 if not total else (parte / total) * 100
