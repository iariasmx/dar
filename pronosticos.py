import mysql.connector
import pandas as pd
import re
from prophet import Prophet

from config import db_config


# 2. Función para normalizar el Ancho de Banda a formato numérico (Mbps)
def limpiar_ancho_banda(valor_str):
    try:
        if not valor_str:
            return None
        # Extraer solo los números del string
        numeros = re.findall(r'\d+\.?\d*', str(valor_str))
        if not numeros:
            return None
        valor_num = float(numeros[0])

        # Convertir Gbps a Mbps si el texto lo indica
        if 'gb' in str(valor_str).lower():
            return valor_num * 1000
        return valor_num
    except Exception:
        return None


# 3. Consulta SQL adaptada a tus campos
# Analizaremos una interfaz específica usando su ID_INTERFACE
ID_A_ANALIZAR = 545705

query = f"""
    SELECT 
        FECHA_SNAP as ds,
        ANCHO_BANDA,
        TRAFICO_95 as trafico
    FROM HISTORICO_DSL_INTERFACE
    WHERE ID_INTERFACE = {ID_A_ANALIZAR}
    ORDER BY FECHA_SNAP ASC;
"""

# 4. Extracción y preparación de los datos
try:
    conexion = mysql.connector.connect(**db_config)
    df_raw = pd.read_sql(query, conexion)
    conexion.close()
except Exception as e:
    print(f"❌ Error al conectar o consultar MySQL: {e}")
    exit()

if df_raw.empty:
    print(f"❌ No se encontraron datos para la interfaz ID: {ID_A_ANALIZAR}")
    exit()

# Limpiar el ancho de banda y calcular el porcentaje de ocupación ('y')
df_raw['capacidad_mbps'] = df_raw['ANCHO_BANDA'].apply(limpiar_ancho_banda)

# Evitar división por cero o nulos
df_raw = df_raw.dropna(subset=['capacidad_mbps', 'trafico'])
df_raw = df_raw[df_raw['capacidad_mbps'] > 0]

# Calculamos 'y' (Ocupación de 0 a 100)
# Ajusta si tu TRAFICO_95 ya está en la misma unidad que ANCHO_BANDA
df_raw['y'] = (df_raw['trafico'] / df_raw['capacidad_mbps']) * 100

# Armar el DataFrame final requerido por Prophet (columnas 'ds' e 'y')
df_ml = df_raw[['ds', 'y']].copy()
df_ml['ds'] = pd.to_datetime(df_ml['ds']).dt.tz_localize(None)

print(f"📊 Datos listos para procesar. Historial cargado: {len(df_ml)} registros.")

# 5. Entrenamiento del Modelo de Machine Learning
# Desactivamos estacionalidades pesadas si los datos cubren pocos meses
model = Prophet(yearly_seasonality=False, daily_seasonality=False, weekly_seasonality=True)
model.fit(df_ml)

# 6. Pronóstico a futuro (90 días)
DIAS_A_PREDECIR = 90
UMBRAL_CRITICO = 85.0  # Alerta si supera el 85% de capacidad

future = model.make_future_dataframe(periods=DIAS_A_PREDECIR, freq='D')
forecast = model.predict(future)

# 7. Evaluar e identificar fecha de colapso de capacidad
futuro_solo = forecast.tail(DIAS_A_PREDECIR)
saturados = futuro_solo[futuro_solo['yhat'] >= UMBRAL_CRITICO]

print("\n================ REPORTING DE CAPACIDAD ================")
print(f"Análisis para Interfaz ID: {ID_A_ANALIZAR}")

if not saturados.empty:
    fecha_alerta = saturados['ds'].iloc[0].strftime('%Y-%m-%d')
    print(f"⚠️  ALERTA DE CRECIMIENTO: El percentil 95 cruzará el umbral del {UMBRAL_CRITICO}% el: {fecha_alerta}")
    print("Recomendación: Planificar ampliación de ancho de banda o rebalanceo de rutas.")
else:
    print(
        f"✅ CAPACIDAD OPTIMA: La interfaz se mantendrá por debajo del {UMBRAL_CRITICO}% los próximos {DIAS_A_PREDECIR} días.")
print("========================================================")
