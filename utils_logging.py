"""
Módulo de utilidades para logging y registro del sistema de trading.
"""

import time
import os
import sys
import shutil
import inspect
import traceback
from datetime import datetime
from typing import Optional

# Configuración global del módulo
LOG_FILE = "registro_general.txt"
DEBUG_MODE = False
CALLER_INFO_LEVEL = 1  # 0=Sin info, 1=Básico, 2=Detallado, 3=Stack completo

# Rotación automática: si un log supera este tamaño se archiva solo antes de seguir
# escribiendo. Es una red de seguridad para que ningún archivo crezca sin control
# aunque se olvide llamar a rotar_logs_al_iniciar().
ROTACION_MAX_BYTES = 2_000_000  # 2 MB
CARPETA_HISTORIAL = "logs/historial_logs"

# Nombre del log cuando NO se puede deducir el módulo llamador. Antes era
# 'registro_AE_BITCOIN.txt' (el log del asesor del bloque aparcado), y por eso todo lo
# que venía de scripts de prueba o de `python -c` contaminaba ese archivo.
DEFAULT_LOG_FILE = "registro_general.txt"

# Ruta absoluta de este archivo: se usa para saltarse los frames internos al deducir
# quién llamó a imprimir().
ARCHIVO_UTILS = os.path.abspath(__file__)

# Añadir al inicio del archivo utils_logging.py
CLASS_LOG_FILES = {
    "BokehChartManager": "registro_BOKEH.txt",
    "AsesorExperto": "registro_AE_BITCOIN.txt",
    "SimpleHandler": "registro_DATOS.txt",
    # Puedes agregar más clases y sus archivos correspondientes
}

# Variable para archivo de log por defecto
DEFAULT_LOG_FILE = "registro_general.txt"

# Módulos de ESTE subproyecto (lanzamiento): sus mensajes van a registro_<modulo>.txt.
# Es una copia de `utils_logging.py` del proyecto padre (que es solo el sniper), recortada
# a los módulos que viven aquí: si el subproyecto se saca a su propia carpeta, sigue igual.
MODULOS_PROYECTO = {
    "motor_solana", "master_mosca", "bundler_sybil", "bundler_venta",
    "test_pump_create", "fabrica_identidades", "modo_servicio", "miembros_ops",
    "utils_logging", "dashboard",
}

# Logs que NO pertenecen a un solo proceso: los escriben las librerías compartidas
# desde dentro de quien las arranca. `motor_solana.py` es el caso claro: usa
# `imprimir` pero no tiene bloque `__main__` (nadie lo ejecuta en solitario), así que
# su log lo tiene que rotar el proceso que lo usa. Por eso los puntos de entrada
# llaman a `rotar_logs_del_proceso()` y no a `rotar_logs_al_iniciar()` a secas.
# `miembros_ops` es igual: master_mosca, bundler_sybil y bundler_venta escriben en el
# mismo registro de operaciones, y todos deben rotarlo al arrancar.
LOGS_COMPARTIDOS = ("motor_solana", "miembros_ops", "ejecutor_jito")

def set_caller_info_level(level: int):
    """
    Configura el nivel de información del caller.
    
    Args:
        level (int): 
            0 = Sin información del caller
            1 = Clase.método:línea (básico)
            2 = archivo:clase.método:línea (detallado)
            3 = Stack trace completo
    """
    global CALLER_INFO_LEVEL
    CALLER_INFO_LEVEL = max(0, min(3, level))


def _get_caller_info(level: int = 1) -> str:
    """
    Obtiene información del caller según el nivel especificado.
    
    Args:
        level (int): Nivel de detalle (0-3)
        
    Returns:
        str: Información formateada del caller
    """
    if level == 0:
        return ""
    
    try:
        # Obtener frame del caller (saltar este método y imprimir)
        frame = inspect.currentframe()
        if frame and frame.f_back and frame.f_back.f_back:
            caller_frame = frame.f_back.f_back
            
            filename = caller_frame.f_code.co_filename
            function_name = caller_frame.f_code.co_name
            line_number = caller_frame.f_lineno
            
            # Extraer nombre del archivo
            filename_short = os.path.basename(filename)
            
            # Obtener información de la clase
            class_name = None
            if 'self' in caller_frame.f_locals:
                class_name = caller_frame.f_locals['self'].__class__.__name__
            elif 'cls' in caller_frame.f_locals:
                class_name = caller_frame.f_locals['cls'].__name__
            
            # Formatear según el nivel
            if level == 1:  # Básico: Clase.método:línea
                if class_name:
                    return f"[{class_name}.{function_name}:{line_number}] "
                else:
                    return f"[{function_name}:{line_number}] "
                    
            elif level == 2:  # Detallado: archivo:clase.método:línea
                if class_name:
                    return f"[{filename_short}:{class_name}.{function_name}:{line_number}] "
                else:
                    return f"[{filename_short}:{function_name}:{line_number}] "
                    
            elif level == 3:  # Stack completo
                stack = traceback.extract_stack()[:-2]  # Excluir este método e imprimir
                if len(stack) > 0:
                    last_call = stack[-1]
                    if class_name:
                        basic_info = f"[{class_name}.{function_name}:{line_number}] "
                    else:
                        basic_info = f"[{filename_short}:{function_name}:{line_number}] "
                    
                    # Agregar stack reducido (últimas 3 llamadas)
                    stack_info = " -> ".join([
                        f"{os.path.basename(call.filename)}:{call.name}:{call.lineno}"
                        for call in stack[-3:]
                    ])
                    return f"{basic_info}(Stack: {stack_info}) "
            
    except Exception:
        return "[caller_info_error] "
    finally:
        if 'frame' in locals():
            del frame
    
    return ""

# --- Método para leer configuración desde ordenes.cfg ---
def cargar_configuracion_cfg(cfg_path=None):
    """
    Lee el archivo ordenes.cfg y devuelve un diccionario con la configuración.
    """
    import os, re
    if cfg_path is None:
        cfg_path = os.path.join(os.path.dirname(__file__), "ordenes.cfg")
    config = {}
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"): continue
                match = re.match(r"(\w+)\s*=\s*(.*)", line)
                if match:
                    key, value = match.groups()
                    value = value.strip()
                    # Quitar comillas si existen
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    # Convertir a int o float si es posible
                    if value.isdigit():
                        value = int(value)
                    else:
                        try:
                            value_float = float(value)
                            value = value_float
                        except Exception:
                            pass
                    config[key] = value
    else:
        raise FileNotFoundError(f"No se encontró el archivo de configuración: {cfg_path}")
    return config

def _archivo_llamador() -> Optional[str]:
    """Nombre (sin .py) del primer módulo FUERA de utils_logging que llama.

    Antes el enrutado dependía de `_get_caller_info`, que a nivel 1 devuelve
    `[Clase.metodo:linea]` — sin nombre de archivo —, así que casi todo caía al
    log por defecto y contaminaba `registro_AE_BITCOIN.txt`. Aquí se sube por la
    pila saltando **este archivo** (lo que además funciona con envoltorios como
    `imprimir_debug` o `imprimir_con_separador`).

    Ojo: se compara por archivo, no por carpeta. `utils_logging.py` vive en la raíz
    junto al resto de módulos, así que comparar carpetas hacía que todo el proyecto
    pareciera "interno" y la función devolviera None.
    """
    frame = inspect.currentframe()
    try:
        frame = frame.f_back if frame is not None else None
        while frame is not None:
            archivo = os.path.abspath(frame.f_code.co_filename)
            if archivo != ARCHIVO_UTILS:
                if not os.path.exists(archivo):
                    # Casos como `python -c` (el archivo es '<string>'): se deja que
                    # decida _nombre_desde_script().
                    return None
                base = os.path.splitext(os.path.basename(archivo))[0]
                if os.path.basename(os.path.dirname(archivo)) == "scratch":
                    # Los scripts de prueba se etiquetan aparte para no mezclarlos
                    return f"scratch_{base}"
                return base
            frame = frame.f_back
    except Exception:
        return None
    finally:
        del frame
    return None


def _nombre_desde_script() -> Optional[str]:
    """Nombre del script en ejecución, para `python -c` o entradas sin módulo."""
    try:
        entrada = sys.argv[0] if sys.argv else ""
        if not entrada or entrada in ("-c", "-m", ""):
            return "consola"
        return os.path.splitext(os.path.basename(entrada))[0]
    except Exception:
        return None


def _rotar_por_tamano(ruta: str, maximo: int = None) -> bool:
    """Archiva un log que superó `maximo` bytes y lo deja vacío con encabezado.

    Devuelve True si rotó. Se llama antes de cada escritura: así ningún archivo
    crece sin control aunque el programa olvide rotar al arrancar. `maximo` se lee
    de ROTACION_MAX_BYTES en cada llamada, para poder ajustarlo en las pruebas.
    """
    if maximo is None:
        maximo = ROTACION_MAX_BYTES
    try:
        if not os.path.exists(ruta) or os.path.getsize(ruta) <= maximo:
            return False
        os.makedirs(CARPETA_HISTORIAL, exist_ok=True)
        marca = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.basename(ruta)
        destino = os.path.join(CARPETA_HISTORIAL, base.replace(".txt", f"_auto_{marca}.txt"))
        shutil.copy2(ruta, destino)
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(
                datetime.now().strftime("%H:%M del %d/%m/%Y")
                + f" **** ROTADO POR TAMAÑO (>{maximo} B) - {base} ****\r"
            )
        return True
    except Exception as e:
        print(f"Error al rotar por tamaño {ruta}: {e}")
        return False


def imprimir(cadena, archivo_log=None, end="\n"):
    """Muestra la cadena por consola y la guarda en el log que corresponda.

    El archivo se decide por el módulo que llama (registro_<modulo>.txt), por el
    nombre de script en los programas sueltos y, si no se puede deducir, por
    DEFAULT_LOG_FILE. Nunca escribe en el log de otro bloque.

    Args:
        cadena (str): mensaje a imprimir y registrar
        archivo_log (str, opcional): sufijo/nombre explícito del log
        end (str): terminador de consola (se usa '\\r' para barras de progreso)
    """
    try:
        try:
            print(cadena, end=end, flush=True)
        except Exception:
            pass

        # Las barras de progreso (end="\r") son salida VISUAL, no historia: los bucles
        # de vigilancia las escriben cada segundo y llenaban el log con miles de líneas
        # de "📊 Profit: ...". Los eventos que importan (objetivo logrado, compras,
        # ventas) se registran igual porque no llevan end.
        if end == "\r":
            return

        base_name = _archivo_llamador()
        if base_name is None:
            base_name = _nombre_desde_script()

        # Los nombres de clase históricos siguen teniendo su archivo propio
        if base_name not in MODULOS_PROYECTO and base_name in CLASS_LOG_FILES:
            base_name = None

        if archivo_log:
            if base_name:
                log_file = f"registro_{base_name}_{archivo_log}.txt"
            else:
                log_file = f"registro_{archivo_log}.txt"
        elif base_name:
            log_file = f"registro_{base_name}.txt"
        else:
            log_file = DEFAULT_LOG_FILE

        logs_dir = "logs"
        if not os.path.exists(logs_dir):
            try:
                os.makedirs(logs_dir)
            except Exception as e:
                print(f"Error al crear carpeta de logs: {e}")
                logs_dir = "."

        log_file_path = os.path.join(logs_dir, log_file)
        _rotar_por_tamano(log_file_path)

        caller_info = _get_caller_info(CALLER_INFO_LEVEL)
        with open(log_file_path, "a", encoding="utf-8") as f:
            fecha = datetime.fromtimestamp(time.time()).strftime("%H:%M del %d/%m/%Y")
            f.write(f"{fecha}: {cadena}                                                                                                                                                                                                                                             {caller_info}\r")

    except Exception as e:
        print(f"Error al escribir en el archivo de log: {e}")

def imprimir_con_caller(cadena, incluir_stack=False):
    """
    Versión explícita que siempre incluye información del caller.
    
    Args:
        cadena (str): Mensaje a imprimir
        incluir_stack (bool): Si incluir información del stack
    """
    level = 3 if incluir_stack else 2
    caller_info = _get_caller_info(level)
    
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            ahora = time.time()
            fecha = datetime.fromtimestamp(ahora).strftime("%H:%M del %d/%m/%Y")
            f.write(f"{fecha}: {caller_info}{cadena}\r")
    except Exception as e:
        print(f"Error al escribir en el archivo de log: {e}")


def imprimir_debug_avanzado(cadena, nivel="DEBUG"):
    """
    Función de debug con información detallada del caller.
    
    Args:
        cadena (str): Mensaje a imprimir
        nivel (str): Nivel de debug
    """
    if DEBUG_MODE or nivel != "DEBUG":
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]  # Incluir milisegundos
        caller_info = _get_caller_info(2)  # Nivel detallado
        mensaje_formateado = f"[{timestamp}] [{nivel}] {caller_info}{cadena}"
        
        # Usar el método básico para evitar recursión
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                ahora = time.time()
                fecha = datetime.fromtimestamp(ahora).strftime("%H:%M del %d/%m/%Y")
                f.write(f"{fecha}: {mensaje_formateado}\r")
        except Exception as e:
            print(f"Error al escribir en el archivo de log: {e}")

def set_debug_mode(enabled: bool):
    """Habilita o deshabilita el modo debug."""
    global DEBUG_MODE
    DEBUG_MODE = enabled


def set_log_file(filename: str):
    """Cambia el nombre del archivo de log."""
    global LOG_FILE
    LOG_FILE = filename


def imprimir_debug(cadena, nivel="DEBUG"):
    """
    Función de impresión con niveles de debug.
    
    Args:
        cadena (str): Mensaje a imprimir
        nivel (str): Nivel de debug (DEBUG, INFO, WARNING, ERROR)
    """
    if DEBUG_MODE or nivel != "DEBUG":
        timestamp = datetime.now().strftime("%H:%M:%S")
        mensaje_formateado = f"[{timestamp}] [{nivel}] {cadena}"
        imprimir(mensaje_formateado)


def imprimir_con_separador(cadena, separador="=", longitud=50):
    """
    Imprime un mensaje con separadores decorativos.
    
    Args:
        cadena (str): Mensaje a imprimir
        separador (str): Carácter para el separador
        longitud (int): Longitud de la línea separadora
    """
    linea = separador * longitud
    imprimir(linea)
    imprimir(cadena)
    imprimir(linea)


def imprimir_encabezado(titulo, subtitulo=""):
    """
    Imprime un encabezado formateado.
    
    Args:
        titulo (str): Título principal
        subtitulo (str): Subtítulo opcional
    """
    imprimir_con_separador(f"*** {titulo.upper()} ***", "=", 60)
    if subtitulo:
        imprimir(f"    {subtitulo}")
        imprimir("")


def imprimir_transaccion(tipo_transaccion, detalles):
    """
    Imprime información de transacciones de trading.
    
    Args:
        tipo_transaccion (str): Tipo de transacción (COMPRA, VENTA, CIERRE, etc.)
        detalles (dict): Diccionario con detalles de la transacción
    """
    imprimir_encabezado(f"TRANSACCIÓN: {tipo_transaccion}")
    for clave, valor in detalles.items():
        imprimir(f"  {clave}: {valor}")
    imprimir("")


def limpiar_log():
    """Limpia el archivo de log creando uno nuevo."""
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            ahora = datetime.now()
            encabezado = (
                ahora.strftime("%H:%M del %d/%m/%Y")
                + " ****NUEVO REGISTRO DEL ASESOR EXPERTO****\r"
            )
            f.write(encabezado)
        print("Archivo de log limpiado correctamente")
    except Exception as e:
        print(f"Error al limpiar el archivo de log: {e}")


def obtener_tamaño_log():
    """Obtiene el tamaño del archivo de log en bytes."""
    try:
        return os.path.getsize(LOG_FILE)
    except FileNotFoundError:
        return 0
    except Exception as e:
        print(f"Error al obtener tamaño del log: {e}")
        return 0


def rotar_log(max_size_mb=10):
    """
    Rota el archivo de log si supera el tamaño máximo.
    
    Args:
        max_size_mb (int): Tamaño máximo en MB antes de rotar
    """
    tamaño_actual = obtener_tamaño_log()
    tamaño_max_bytes = max_size_mb * 1024 * 1024
    
    if tamaño_actual > tamaño_max_bytes:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nuevo_nombre = f"{LOG_FILE}.{timestamp}.bak"
        
        try:
            os.rename(LOG_FILE, nuevo_nombre)
            limpiar_log()
            imprimir(f"Log rotado. Archivo anterior: {nuevo_nombre}")
        except Exception as e:
            print(f"Error al rotar el log: {e}")


def log_sistema_iniciado():
    """Registra el inicio del sistema con información relevante."""
    imprimir_encabezado("SISTEMA DE TRADING INICIADO")
    imprimir(f"Fecha y hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    imprimir(f"Archivo de log: {LOG_FILE}")
    imprimir(f"Modo debug: {'Activado' if DEBUG_MODE else 'Desactivado'}")
    imprimir("")


def log_evento_trading(evento, datos):
    """
    Registra eventos específicos de trading.
    
    Args:
        evento (str): Tipo de evento (ORDEN_ABIERTA, CANDADO_FORMADO, etc.)
        datos (dict): Datos del evento
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    imprimir(f"[{timestamp}] EVENTO: {evento}")
    
    for clave, valor in datos.items():
        if isinstance(valor, float):
            imprimir(f"  {clave}: {valor:.4f}")
        else:
            imprimir(f"  {clave}: {valor}")
    imprimir("")

def _normalizar_filtros(filtro):
    """Convierte None, un texto o una lista de textos en una tupla limpia.

    Se admite lista porque un mismo proceso escribe varios logs (el suyo y el de las
    librerías compartidas), y antes había que llamar a `rotar_logs_al_iniciar()` una
    vez por cada uno, lo que se olvidaba con facilidad.
    """
    if filtro is None:
        return ()
    if isinstance(filtro, str):
        return (filtro,) if filtro.strip() else ()
    return tuple(f for f in filtro if isinstance(f, str) and f.strip())


def rotar_logs_al_iniciar(filtro=None, logs_dir="logs/historial_logs", backup_suffix=None):
    """Rota los logs: guarda una copia fechada y deja el original limpio con encabezado.

    Args:
        filtro (str | list[str], optional): nombre (o nombres) de módulo a rotar. Si se
            indica, solo se rotan los logs cuyo nombre contenga alguno de esos textos
            (cada proceso rota el suyo al arrancar). Sin filtro, se rotan todos.
        logs_dir (str, optional): carpeta de respaldo. Por defecto "logs/historial_logs".
        backup_suffix (str, optional): alias histórico del filtro.

    Devuelve la lista de rutas rotadas (lo usan las pruebas para comprobarlo).

    IMPORTANTE: el respaldo SIEMPRE lleva marca de tiempo. Antes, al pasar un filtro, el
    nombre salía sin fecha (p. ej. `registro_master_mosca_master_mosca.txt`), así que cada
    arranque **sobrescribía** el respaldo anterior y se perdían los logs de la sesión
    previa. Ahora se añade `_<filtro>_<fecha_hora>` y, si aun así existe, un contador.
    """
    import glob
    import shutil

    if backup_suffix is not None and filtro is None:
        filtro = backup_suffix
    filtros = _normalizar_filtros(filtro)

    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    sufijo = "_".join(filtros) if filtros else "old"

    # Crear la carpeta de respaldo si no existe
    if not os.path.exists(logs_dir):
        try:
            os.makedirs(logs_dir)
            imprimir(f"Carpeta de logs creada: {logs_dir}")
        except Exception as e:
            imprimir(f"Error al crear carpeta de logs: {e}")
            logs_dir = "."

    # Buscar todos los logs (registro_*.txt) y filtrar por nombre si se pidió
    todos_logs = glob.glob(os.path.join("logs", "registro_*.txt"))
    if filtros:
        log_files = [f for f in todos_logs
                     if any(fil in os.path.basename(f) for fil in filtros)]
    else:
        log_files = todos_logs

    log_files = set(log_files)
    rotados = []

    # Procesar cada archivo
    for log_file in log_files:
        try:
            # Si el archivo existe y tiene contenido
            if os.path.exists(log_file) and os.path.getsize(log_file) > 0:
                # Crear nombre para archivo de respaldo en la carpeta de logs
                base_filename = os.path.basename(log_file)
                backup_name = os.path.join(
                    logs_dir, base_filename.replace(".txt", f"_{sufijo}_{marca}.txt"))
                # Nunca sobrescribir un respaldo: si ya existe, se numera
                contador = 1
                while os.path.exists(backup_name):
                    backup_name = os.path.join(
                        logs_dir,
                        base_filename.replace(".txt", f"_{sufijo}_{marca}_{contador}.txt"))
                    contador += 1
                # Mover archivo actual a la carpeta de logs con el nuevo nombre
                shutil.copy2(log_file, backup_name)
                rotados.append(f"{base_filename} → {os.path.basename(backup_name)}")
                # Limpiar el archivo original
                with open(log_file, "w", encoding="utf-8") as f:
                    ahora = datetime.now()
                    encabezado = (
                        ahora.strftime("%H:%M del %d/%m/%Y")
                        + f" **** NUEVO REGISTRO - {os.path.basename(log_file)} ****\r"
                    )
                    f.write(encabezado)
            else:
                # Si el archivo no existe o está vacío, crearlo
                with open(log_file, "w", encoding="utf-8") as f:
                    ahora = datetime.now()
                    encabezado = (
                        ahora.strftime("%H:%M del %d/%m/%Y")
                        + f" **** NUEVO REGISTRO - {os.path.basename(log_file)} ****\r"
                    )
                    f.write(encabezado)
        except Exception as e:
            imprimir(f"Error al rotar archivo {log_file}: {e}")

    # Registrar la rotación en los nuevos logs
    try:
        for log_file in log_files:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%H:%M del %d/%m/%Y')}: ✅ Logs anteriores guardados en carpeta {logs_dir}\r")
    except Exception as e:
        imprimir(f"Error al registrar rotación: {e}")

    # El aviso se imprime AL FINAL, no dentro del bucle de copia. Antes se escribía
    # cuando el archivo original todavía no se había vaciado, así que la línea caía en
    # el log viejo y se perdía al truncarlo: en el log nuevo no quedaba rastro de la
    # rotación. Ahora queda en el log recién creado del proceso que arrancó.
    if rotados:
        imprimir("🗂️ Logs rotados: " + " | ".join(sorted(rotados)))

    return rotados


def rotar_logs_del_proceso(modulo, extras=None):
    """Rota el log del módulo que arranca MÁS los de las librerías compartidas.

    Regla del proyecto: todo módulo que use `imprimir()` rota su log al arrancar (no al
    importarse). Como las librerías no arrancan solas, ese trabajo lo hace quien las
    arranca con esta función.

    Args:
        modulo (str): nombre del módulo que arranca, p. ej. "dashboard".
        extras (list[str], optional): otros logs que ese proceso vaya a escribir, p. ej.
            master_mosca también usa `fabrica_identidades`.

    Devuelve la lista de rutas rotadas.
    """
    filtros = [modulo, *LOGS_COMPARTIDOS, *(extras or [])]
    return rotar_logs_al_iniciar(filtros)


# Lista de todas las funciones disponibles para importación con *
