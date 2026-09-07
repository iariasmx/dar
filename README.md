# Diseño y Anális de Red (DAR)

Proyecto en Python para consultar inventario de infraestructura de red en MySQL, visualizarlo con Streamlit, guardar históricos de interfaces y estimar su ocupación futura con Prophet.

El punto de entrada principal es `app.py`. Los dashboards consultan datos existentes; la carga del inventario y de las mediciones debe realizarse mediante un proceso externo. El proyecto incluye el esquema SQL, pero no datos de ejemplo ni un importador.

## Estructura del proyecto

| Archivo | Función |
| --- | --- |
| `app.py` | Dashboard principal con inventario, capacidad, interfaces L1, ubicación y conciliación. |
| `inventario.py` | Dashboard independiente de tarjetas y subtarjetas, con filtros por sitio, modelo de equipo y equipo. |
| `snapshot.py` | Copia el estado de interfaces activas a la tabla histórica. |
| `pronosticos.py` | Entrena Prophet para una interfaz y muestra un pronóstico en consola. |
| `main.py` | Plantilla de PyCharm: imprime un saludo; no inicia la aplicación. |
| `docker-compose.yml` | Servicio MySQL y volumen persistente. No contiene un servicio para Streamlit. |
| `docker/mysql/init/DatabaseSchemaManagement.sql` | Creación de la base de datos, tablas e índices. |
| `graficas.py` | Gráficas de barras horizontales con Plotly compartidas por ambos dashboards. |
| `sesiones.py` | Consulta y pestaña de sesiones Infinitum con filtros propios. |
| `config.py` | Carga y valida la configuración compartida de MySQL. |
| `.env.example` | Plantilla para crear el archivo local `.env`. |
| `requirements.txt` | Dependencias de los dashboards y del snapshot; Prophet se instala por separado. |

## Requisitos e instalación

- Python y `pip`. No hay una versión de Python declarada; `requirements.txt` enumera las dependencias sin fijar versiones. Para un entorno nuevo se recomienda Python 3.11 o 3.12, verificando la compatibilidad de las versiones instaladas, especialmente Prophet.
- MySQL accesible desde el equipo donde se ejecuta Python.
- Docker y Docker Compose si se utiliza la base de datos incluida.

Desde la raíz del proyecto, crear y activar un entorno virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

En Windows, activar el entorno con `.venv\Scripts\activate` desde CMD o `.venv\Scripts\Activate.ps1` desde PowerShell.

Para ejecutar pronósticos, instalar además:

```bash
python -m pip install prophet
```

`io` y `re`, utilizados por el código, pertenecen a la biblioteca estándar de Python.

## Configuración de MySQL

Los cuatro módulos operativos (`app.py`, `inventario.py`, `snapshot.py` y `pronosticos.py`) importan `db_config` desde `config.py`. Este módulo utiliza `python-dotenv` para cargar el archivo `.env` de la raíz del proyecto, independientemente del directorio desde el que se ejecute Python.

Si todavía no existe un archivo `.env`, crearlo desde la plantilla:

```bash
cp .env.example .env
```

En Windows puede copiarse el archivo desde el explorador. Editar `.env` con los parámetros de la conexión:

```dotenv
DB_HOST=localhost
DB_PORT=3306
DB_NAME=dbIngenieria
DB_USER=tu_usuario
DB_PASSWORD=tu_contrasena
```

La plantilla conserva los valores de la configuración local existente. Las variables ya definidas en el entorno del proceso tienen prioridad sobre `.env`. `DB_HOST`, `DB_NAME`, `DB_USER` y `DB_PASSWORD` son obligatorias y no pueden estar vacías. `DB_PORT` utiliza `3306` si se omite y debe ser un entero entre 1 y 65535. Una configuración inválida detiene el inicio con un mensaje que identifica las variables, sin mostrar contraseñas.

Si una contraseña contiene espacios o `#`, escribir su valor entre comillas. `.env` está excluido mediante `.gitignore`; no debe compartirse ni subirse al repositorio. Reiniciar los procesos de Python o Streamlit después de modificarlo para recargar la configuración y las consultas en caché.

El archivo `.env` configura los clientes Python. `docker-compose.yml` todavía define las credenciales del servidor con valores literales: si se cambian los usuarios o contraseñas de MySQL, actualizar también `.env` para que coincida. Cambiar `.env` no crea usuarios ni modifica contraseñas de una base existente. El servicio define además `dbingenieria_user`, que puede utilizarse configurando sus credenciales en `.env`.

### Base de datos con Docker

```bash
docker compose up -d
docker compose ps
docker compose logs mysql-db
```

El servicio `mysql-db` crea el contenedor `dbingenieria-mysql`, publica el puerto `3306`, utiliza la zona horaria `America/Mexico_City` y conserva los datos en el volumen `dbingenieria_data` administrado por Compose. Ajustar el puerto publicado y `DB_PORT` en `.env` si el puerto local ya está ocupado.

El directorio `docker/mysql/init` se monta en `/docker-entrypoint-initdb.d`. MySQL ejecuta sus scripts al inicializar un directorio de datos vacío; reiniciar un volumen existente no vuelve a aplicar el esquema.

Para abrir una sesión SQL y comprobar las tablas, introducir la contraseña configurada cuando se solicite:

```bash
docker compose exec mysql-db mysql -u root -p dbIngenieria
```

```sql
SHOW TABLES;
SELECT COUNT(*) FROM SIRU_DSL;
SELECT COUNT(*) FROM EQUIPOS_DSL_INTERFACE_L1;
SELECT COUNT(*) FROM HISTORICO_DSL_INTERFACE;
```

Para detener los contenedores conservando los datos:

```bash
docker compose down
```

### MySQL existente

Aplicar el esquema desde la raíz del proyecto, con un usuario que tenga permisos para crear la base de datos y sus tablas:

```bash
mysql -h localhost -P 3306 -u root -p < docker/mysql/init/DatabaseSchemaManagement.sql
```

El SQL utiliza `CREATE ... IF NOT EXISTS`; no es un sistema de migraciones y no modifica la estructura de tablas ya existentes.

## Modelo de datos

| Tabla | Contenido y uso |
| --- | --- |
| `SIRU_DSL` | Inventario lógico: divisional, sitio, equipo, modelo, tarjetas, slots, puertos, asignación y ubicación física. Fuente de ambos dashboards. |
| `EQUIPOS_DSL_INTERFACE_L1` | Identificadores de interfaz y equipo, slot, estado administrativo, IP, VLAN, ancho de banda y tráfico. Fuente de auditoría y snapshots. |
| `HISTORICO_DSL_INTERFACE` | Mediciones copiadas por `snapshot.py`, con clave `ID_HISTORICO` y `FECHA_SNAP` asignada por MySQL mediante `CURRENT_TIMESTAMP`. Fuente del pronóstico. |

Las tablas de origen tienen índices, pero no claves primarias ni restricciones de unicidad. El esquema no declara claves foráneas. La calidad de los identificadores y la prevención de duplicados dependen del proceso de carga.

Los dashboards seleccionan únicamente filas con `NOMBRE_EQUIPO IS NOT NULL` y `STATUS_EQUIPO != 'BAJA'`. Por la semántica de SQL, también quedan excluidas las filas cuyo estado sea `NULL`. Conviene proporcionar sitio, modelo y campos de agrupación consistentes para evitar registros omitidos o errores durante la presentación.

## Uso del dashboard principal

```bash
python -m streamlit run app.py
```

Abrir la dirección indicada por Streamlit, normalmente `http://localhost:8501`.

Ambos dashboards utilizan Plotly para las gráficas de los diez números de parte predominantes. Las barras horizontales muestran cantidades y detalles al pasar el cursor, con herramientas para ampliar y descargar la imagen. Cuando no hay datos, se muestra un mensaje en lugar de una gráfica vacía.

El botón **Limpiar filtros** de la barra lateral restablece divisional, sitio, modelo y equipo a `TODOS`, vacía la búsqueda por IP/VLAN y restablece el filtro de tipo de asignación del detalle de ocupados.

La barra lateral permite filtrar en cascada por divisional, sitio Uninet, modelo de equipo y nombre de equipo. El modelo corresponde a `MODELO` de `SIRU_DSL` (alias `MODELO_EQUIPO`); sus opciones dependen del sitio y divisional seleccionados, y restringen la lista de equipos. La opción `TODOS` permite incluir todos los modelos. Este filtro se aplica a las cinco pestañas y a la conciliación exportada; en L1 se conserva la relación por slots descrita más adelante. El buscador por IP o VLAN se aplica a las vistas de interfaces y conciliación que contienen esos campos.

| Pestaña | Información presentada |
| --- | --- |
| Números de Parte de Hardware | Matriz de tarjetas y subtarjetas, con los diez números de parte predominantes según el filtro. |
| Capacidad y Estado de Puertos | Conteos de puertos ocupados, libres y reservados, y ocupación por equipo. |
| Interfaces Capa 1 (L1) | Interfaces de los slots seleccionados, IP, VLAN, protocolo, ancho de banda y estado administrativo. |
| Ubicación y Datos Maestros | Una fila por nombre de equipo con piso, sala, fila, elemento de fila, patch panel y atributos de gestión. |
| Conciliación Cruzada (SIRU vs L1) | Cruce de asignaciones por slot con interfaces, alertas, tráfico promedio y conteo de métricas `OK_MET = 'SI'`. |

En **Capacidad y Estado de Puertos**, los botones **Ver puertos ocupados**, **Ver puertos libres** y **Ver puertos reservados**, debajo de cada contador, abren un popup con el detalle correspondiente. Incluyen equipo, modelo, chasis, slot, subslot, puerto, tipo de asignación, números de parte, descripción y posiciones de remate (piso, sala, fila, elemento de fila, patch panel y `POS_REMATE`), en lugar de ubicación. El detalle respeta los filtros de divisional, sitio, modelo y equipo, y utiliza la misma clasificación que los contadores. Cada botón queda deshabilitado cuando su contador es cero. El popup de ocupados incluye un desglose de cantidades por `TIPO_ASIG` y un selector para consultar los puertos de cada tipo; el desglose conserva los totales de los filtros del dashboard.

El botón lateral exporta la conciliación filtrada como `conciliacion_siru_vs_l1.csv`, en UTF-8 y sin índice. Solo aparece si esa vista contiene filas; no exporta todas las pestañas.

### Criterios de cálculo y alcance

- La capacidad excluye los puertos de procesadoras: subtarjetas Juniper cuyo `NUM_PARTE_SUBTARJETA` comienza con `RE-` y tarjetas Cisco cuyo `NUM_PARTE_TARJETA` contiene `RSP`. La comparación ignora mayúsculas y minúsculas y utiliza los números de parte sin espacios externos. La exclusión afecta a conteos, porcentajes, desglose por asignación y popups de capacidad; las tarjetas siguen visibles en el inventario de hardware.
- La capacidad considera filas con `PUERTO` no vacío. Después de quitar espacios externos y convertir a mayúsculas, solo `TIPO_ASIG = LIBRE` se cuenta como libre. Los valores que contienen `RESERVADO` se cuentan como reservados y el resto como ocupados, excepto valores vacíos, nulos o `SIN TIPO_ASIG`. Estos últimos permanecen en el total de puertos, pero no cuentan como ocupados, libres ni reservados, y no aparecen en el desglose ni en el popup de ocupados. Los puertos se cuentan por fila, sin deduplicación.
- La ocupación se calcula como ocupados / total × 100 y se muestra con un decimal y el símbolo `%`. La barra utiliza una escala de 0 a 100; por ejemplo, 3 puertos ocupados de 4 se muestran como `75.0%`.
- La conciliación agrupa SIRU por divisional, sitio, equipo, modelo y slot, y realiza un `inner join` con L1 **solo por `SLOT`**. Slots iguales de distintos equipos pueden mezclarse o multiplicar filas. Los registros sin coincidencia quedan fuera del resultado; el filtrado L1 también se basa solo en slots.
- En la conciliación, cualquier `TIPO_ASIG` distinto de `LIBRE` se cuenta como asignado, incluidos reservados y cadenas vacías. Este criterio difiere del cálculo de capacidad.
- Se genera alerta cuando hay asignaciones y `SHUTDOWN = 1`, o cuando no hay asignaciones y existe una IP. Las demás coincidencias se etiquetan como alineadas; esa etiqueta no valida todos los atributos del enlace.
- El indicador de interfaces activas del dashboard usa `SHUTDOWN = 0`, no una comprobación del estado operativo `STATUS`.
- El buscador utiliza `str.contains` con expresiones regulares activadas: los puntos de una IP y otros caracteres especiales no se interpretan necesariamente como texto literal.

## Dashboard de inventario independiente

```bash
python -m streamlit run inventario.py
```

Para ejecutarlo junto al dashboard principal:

```bash
python -m streamlit run inventario.py --server.port 8502
```

Muestra tarjetas y subtarjetas por equipo, slot y subslot. Los filtros por sitio, modelo de equipo y equipo afectan a la tabla; sus indicadores generales y gráficas de los diez modelos predominantes se calculan sobre el inventario completo. Los equipos sin número de parte de tarjeta no forman parte de esa matriz.

## Captura de histórico

```bash
python snapshot.py
```

Cada ejecución selecciona interfaces cuyo `STATUS = 'UP'` **o** `SHUTDOWN = 0`, e inserta `ID_INTERFACE`, `ID_EQUIPO`, `SLOT`, `ANCHO_BANDA` y `TRAFICO_95` en `HISTORICO_DSL_INTERFACE`. La fecha la asigna MySQL y las inserciones se confirman con `commit`.

El script escribe en la base de datos. No realiza deduplicación: ejecutarlo varias veces genera nuevas observaciones de las mismas interfaces. No incluye un programador; para construir una serie temporal debe ejecutarse periódicamente mediante una herramienta externa, como cron o el Programador de tareas.

## Pronóstico de capacidad

Con datos históricos disponibles y Prophet instalado:

```bash
python pronosticos.py
```

Los parámetros se editan directamente en `pronosticos.py`; no hay argumentos de línea de comandos:

| Parámetro | Valor actual | Uso |
| --- | --- | --- |
| `ID_A_ANALIZAR` | `545705` | Interfaz que se consulta en el histórico. |
| `DIAS_A_PREDECIR` | `90` | Número de días futuros. |
| `UMBRAL_CRITICO` | `85.0` | Umbral de ocupación porcentual. |

El script extrae la primera cifra de `ANCHO_BANDA`, multiplica por 1000 si el texto contiene `gb` y trata los demás valores numéricos como Mbps. Por tanto, otras unidades requieren normalización previa. `TRAFICO_95` debe estar en Mbps para calcular correctamente `tráfico / capacidad × 100`.

Descarta registros sin capacidad o tráfico y capacidades no positivas. Entrena Prophet con estacionalidad semanal habilitada y estacionalidades diaria y anual deshabilitadas. Se necesitan al menos dos observaciones válidas en fechas distintas para el ajuste básico; la utilidad del pronóstico depende de la extensión, frecuencia y calidad del histórico.

La salida en consola informa la primera fecha futura cuya estimación `yhat` alcanza o supera el umbral, o indica que no lo cruza en el horizonte analizado. No guarda resultados, genera gráficas ni envía notificaciones. El resultado es una estimación del modelo, sin evaluación de precisión implementada en el proyecto.

## Limitaciones y resolución de problemas

- **MySQL no arranca:** revisar los logs y retirar la opción de autenticación incompatible con MySQL 8.4 descrita anteriormente.
- **Error de conexión:** comprobar servidor, puerto, credenciales y nombre de base en `.env`, así como posibles variables de entorno que tengan prioridad. Cambiar `.env.example` no modifica un `.env` existente.
- **Dashboard sin datos:** el esquema inicial crea tablas vacías. Cargar datos de origen y comprobar que cumplan los filtros de nombre y estado del equipo.
- **Datos desactualizados:** las lecturas de ambos dashboards usan `st.cache_data` sin caducidad configurada. Limpiar la caché de Streamlit y volver a ejecutar la aplicación después de actualizar MySQL.
- **Fallo al consultar L1:** `app.py` devuelve un DataFrame sin columnas ante una excepción y después intenta cruzarlo por `SLOT`; esto puede provocar un error adicional. La consulta L1 debe funcionar para completar el procesamiento principal.
- **Histórico insuficiente:** el pronóstico no valida cuántos registros quedan después de la limpieza ni captura errores de entrenamiento de Prophet.

No se incluyen pruebas automatizadas, archivo de dependencias con versiones fijadas, migraciones ni configuración de despliegue de la aplicación. Las instrucciones y los comportamientos descritos se basan en la revisión estática del código; no constituyen una validación de ejecución con una base de datos poblada.

La consulta de inventario incluye `POS_REMATE` cuando existe en `SIRU_DSL`. En bases antiguas sin esa columna devuelve un valor nulo para mantener operativo el detalle; no deduce la posición a partir de la ubicación. El esquema de nuevas instalaciones incluye el campo. Para agregarlo a una base existente que aún no lo tenga, ejecutar una sola vez:

```sql
ALTER TABLE dbIngenieria.SIRU_DSL ADD COLUMN POS_REMATE VARCHAR(255) NULL;
```

Después de actualizar el esquema o cargar posiciones, limpiar la caché de Streamlit para volver a consultar los datos.

## Sesiones Infinitum

La pestaña **Sesiones Infinitum** consulta `INFINITUM_dslSessionSemanal` mediante la conexión de `.env`. Excluye en SQL cualquier `SLOT` que contenga un punto, así como slots nulos o vacíos. Quita el apóstrofo inicial del slot para mostrarlo. Aplica los filtros laterales de divisional, sitio, modelo y equipo, comparando `HOSTNAME` con los `NOMBRE_EQUIPO` del inventario filtrado. La comparación utiliza el nombre corto anterior al primer punto, ignorando mayúsculas y espacios externos; por ejemplo, `ipdsl-ags-pedroparga-14` coincide con `ipdsl-ags-pedroparga-14.gdl`. El detalle conserva el hostname completo. Se presupone que el nombre corto identifica al mismo equipo entre dominios. No multiplica las sesiones por las filas de inventario. Incluso con `TODOS`, solo incluye equipos presentes en el inventario SIRU cargado. El selector local `TIPO` permite restringir adicionalmente el tipo de interfaz y **Limpiar filtros** también lo restablece. La búsqueda IP/VLAN no se aplica a sesiones porque no hay una relación fiable disponible entre esos campos y hostname.

Muestra el total de sesiones, equipos, interfaces, sesiones por hostname y detalle descargable en CSV. `MAX_USER_SESSION` se valida como entero no negativo: los valores vacíos o inválidos se advierten y quedan fuera de las sumas. Las interfaces repetidas por hostname, tipo y slot se advierten sin eliminar registros automáticamente.

Con los seis registros del ejemplo, se incluyen `2/0/0:0`, `2/0/0:1` y `2/1/0:0`: **1138 + 1461 + 755 = 3354 sesiones**. Las subinterfaces con `.1776`, `.1777` y `.1773` quedan excluidas. La suma de máximos por interfaz no equivale necesariamente a un máximo simultáneo del equipo; la tabla no incluye fechas para seleccionar semanas ni reconstruir históricos.

La consulta usa caché de cinco minutos y el botón **Actualizar sesiones** fuerza una lectura nueva. Los filtros y la actualización se ejecutan en un fragmento de Streamlit para evitar recalcular el dashboard completo. Un error al consultar esta tabla se muestra dentro de la pestaña. El inicio de la aplicación continúa dependiendo de los datos SIRU y L1 existentes.
