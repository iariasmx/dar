# pronosticos.py
import pandas as pd
from prophet import Prophet


def obtener_y_limpiar_datos(interface_hostname, metric_column, engine):
    """
    Se conecta a MySQL, extrae el histórico desde PERCENTIL_HISTORICO
    y formatea el DataFrame con las columnas 'ds' y 'y' requeridas por Prophet.
    """
    query = f"""
        SELECT periodo, CAST(NULLIF(`{metric_column}`, '') AS DECIMAL(10,2)) AS valor
        FROM PERCENTIL_HISTORICO
        WHERE interface_hostname = %s AND `{metric_column}` IS NOT NULL
    """

    df = pd.read_sql(query, engine, params=(interface_hostname,))

    if df.empty:
        return pd.DataFrame()

    df['fecha_str'] = df['periodo'].str.extract(r'([0-9]{4}-[0-9]{2}-[0-9]{2})')
    df['ds'] = pd.to_datetime(df['fecha_str'])
    df['y'] = df['valor'].astype(float)

    df = df.dropna(subset=['ds', 'y']).sort_values('ds')

    # ======================================================================
    # 🔥 ¡AQUÍ ESTÁ EL CAMBIO!
    # Filtramos los valores en cero para que la tendencia no se arrastre al fondo
    # y modele basándose puramente en tus ráfagas activas de tráfico.
    df = df[df['y'] > 0]
    # ======================================================================

    return df[['ds', 'y']]


def generar_prediccion_prophet(df_limpio, semanas_futuro=12):
    """
    Entrena el modelo Prophet adaptado a métricas de red semanales.
    Soporta ejecuciones rápidas desde un mínimo de 2 semanas de histórico.
    """
    if len(df_limpio) < 2:
        return None, None

    if df_limpio['y'].nunique() <= 1:
        import numpy as np
        futuro_ds = pd.date_range(start=df_limpio['ds'].max(), periods=semanas_futuro + 1, freq='W')[1:]
        valor_constante = df_limpio['y'].iloc[0]

        df_historico_falso = pd.DataFrame({
            'ds': df_limpio['ds'], 'yhat': valor_constante, 'yhat_upper': valor_constante, 'yhat_lower': valor_constante
        })
        df_futuro_falso = pd.DataFrame({
            'ds': futuro_ds, 'yhat': valor_constante, 'yhat_upper': valor_constante, 'yhat_lower': valor_constante
        })

        forecast_falso = pd.concat([df_historico_falso, df_futuro_falso], ignore_index=True)
        return "CONSTANTE", forecast_falso

    activar_anual = len(df_limpio) >= 26

    model = Prophet(
        yearly_seasonality=activar_anual,
        weekly_seasonality=False,
        daily_seasonality=False,
        interval_width=0.95,

        changepoint_prior_scale=0.8,
        seasonality_prior_scale=10.0,
        n_changepoints=40,
        mcmc_samples=0
    )

    try:
        model.fit(df_limpio, algorithm='LBFGS')
    except Exception:
        try:
            model.fit(df_limpio, algorithm='Newton')
        except Exception:
            return None, None

    future = model.make_future_dataframe(periods=semanas_futuro, freq='W')
    forecast = model.predict(future)

    return model, forecast
