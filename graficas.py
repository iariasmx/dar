"""Gráficas compartidas para los dashboards de inventario."""

import plotly.graph_objects as go
import streamlit as st


def mostrar_top_modelos(conteos, *, key):
    """Presenta los conteos recibidos sin generar una marca por cada unidad."""
    if conteos.empty:
        st.info('No hay datos para graficar con la selección actual.')
        return

    modelos = conteos.index.astype(str).tolist()
    cantidades = conteos.tolist()
    # Las barras usan el color principal configurado; Streamlit adapta el resto
    # (fondos, textos y ejes) al tema activo en el navegador.
    tipo_tema = st.context.theme.type
    color_principal = (
        st.get_option(f'theme.{tipo_tema}.primaryColor')
        if tipo_tema in ('light', 'dark') else None
    ) or st.get_option('theme.primaryColor')
    figura = go.Figure(
        data=[go.Bar(
            x=cantidades,
            y=modelos,
            orientation='h',
            text=cantidades,
            textposition='auto',
            marker=dict(color=color_principal),
            hovertemplate='Número de parte: %{y}<br>Cantidad: %{x}<extra></extra>',
        )],
        layout=go.Layout(
            template='streamlit',
            xaxis=dict(
                title='Cantidad de registros',
                tickmode='auto',
                nticks=6,
                tickformat=',.0f',
                rangemode='tozero',
            ),
            yaxis=dict(
                title='Número de parte',
                type='category',
                categoryorder='array',
                categoryarray=modelos,
                autorange='reversed',
                automargin=True,
            ),
            height=450,
            margin=dict(l=10, r=20, t=20, b=40),
        ),
    )
    st.plotly_chart(figura, width="content", key=key, theme='streamlit')
