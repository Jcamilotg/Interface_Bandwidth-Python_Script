#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Interface Bandwidth Tester (fixed, with logging + no-freeze sync)
# - Replaces global Barrier with per-test Event to avoid deadlocks.
# - Adds robust logging to console and file.
# - Keeps CSV and live matplotlib charting.

import socket
import time
import csv
import threading
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import deque
from datetime import datetime
import matplotlib.lines as mlines
import os
import logging
import sys

# =============================
# Logging configuration
# =============================
LOG_FILE = "detallado.log"
logging.basicConfig(
    level=logging.DEBUG,  # DEBUG for deep detail; change to INFO if too noisy
    format="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8")
    ]
)

logger = logging.getLogger(__name__)

# =============================
# Interface selection (mapping)
# =============================
INTERFACES = {
    1: ("Wi-Fi 2.4GHz", 0.4),
    2: ("Wi-Fi 5GHz", 2.0),
    3: ("Wi-Fi 6GHz", 3.0),
    4: ("Wi-Fi 7", 7.0),
    5: ("Ethernet 1 Gbps", 1.0),
    6: ("Ethernet 2.5 Gbps", 2.5),
    7: ("Ethernet 5 Gbps", 5.0),
    8: ("Ethernet 10 Gbps", 10.0),
}

print('''
    Seleccione Interfaz o Estandar a Validar:

    [1] Wi-Fi 2.4GHz
    [2] Wi-Fi 5GHz 
    [3] Wi-Fi 6GHz
    [4] Wi-Fi 7
    [5] Ethernet 1 Gbps
    [6] Ethernet 2.5 Gbps
    [7] Ethernet 5 Gbps
    [8] Ethernet 10 Gbps
''')

try:
    opcion = int(input("Ingrese la opción deseada: \t").strip())
    if opcion not in INTERFACES:
        raise ValueError("Opción fuera de rango")
    nombre_iface, interface = INTERFACES[opcion]
    print(f"[{opcion}] {nombre_iface}")
    logger.info(f"Interfaz seleccionada: {nombre_iface} (límite {interface*1000:.0f} Mbps)")
except Exception as e:
    print(f"Error al leer la opción: {e}")
    logger.exception("Error seleccionando interfaz")
    sys.exit(1)

# =============================
# Configuración principal
# =============================
DEST_IP = "192.168.75.254"
PORT = 5001
PACKET_SIZE = 65000    # 65 KB
DURATION = 15          # segundos por prueba
NUM_THREADS = 10       # hilos concurrentes para generar carga

nombre_archivo = input("\nIngrese Nombre del archivo Log a guardar: \t").strip() or "pruebas"
try:
    Numerotest = int(input("\nIngrese número de pruebas, si quiere infinitos agregue '0': \t").strip())
except Exception:
    Numerotest = 0  # por defecto, infinitas

logger.info(f"Destino UDP: {DEST_IP}:{PORT} | Packet={PACKET_SIZE}B | Duración={DURATION}s | Threads={NUM_THREADS}")
logger.info(f"Archivo base: {nombre_archivo} | Numerotest={Numerotest if Numerotest else '∞'}")

pruebas = 0
num_fallas = 0

# Historial
CSV_FILE = f"{nombre_archivo}.csv"
if not os.path.exists(CSV_FILE) or os.path.getsize(CSV_FILE) == 0:
    with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["Fecha", "Hora", "Ancho de Banda (Mbps)"])

MAX_POINTS = 5000
times = deque(maxlen=MAX_POINTS)
bandwidths = deque(maxlen=MAX_POINTS)

# =============================
# Worker de envío (sin Barrier; con Event)
# =============================
def enviar_paquetes(thread_id, result_list, start_event):
    # Envía paquetes UDP durante DURATION, al activarse el evento start_event.
    # No hace sleep largo previo, para evitar sensación de cuelgue.
    # Maneja errores para no romper toda la prueba.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, min(1_048_576, PACKET_SIZE * 4))
        logger.debug(f"[T{thread_id}] Socket creado")
    except Exception as e:
        logger.exception(f"[T{thread_id}] Error creando socket: {e}")
        result_list[thread_id] = 0
        return

    # Esperar banderazo de salida
    start_event.wait(timeout=10)  # evita esperar infinito
    if not start_event.is_set():
        logger.error(f"[T{thread_id}] Start event no se activó a tiempo")
        result_list[thread_id] = 0
        return

    start_time = time.time()
    bytes_sent = 0

    while time.time() - start_time < DURATION:
        try:
            sock.sendto(b'X' * PACKET_SIZE, (DEST_IP, PORT))
            bytes_sent += PACKET_SIZE
        except socket.error as e:
            logger.error(f"[T{thread_id}] socket.error durante envío: {e}")
            result_list[thread_id] = 0
            return
        except Exception as e:
            logger.exception(f"[T{thread_id}] Excepción durante envío: {e}")
            result_list[thread_id] = 0
            return

    elapsed = time.time() - start_time
    if bytes_sent == 0 or elapsed < 1:
        logger.warning(f"[T{thread_id}] Sin tráfico útil o duración corta (elapsed={elapsed:.2f})")
        result_list[thread_id] = 0
        return

    bandwidth_mbps = (bytes_sent * 8) / (elapsed * 1_000_000)

    if bandwidth_mbps > 10000:  # umbral anti-valores absurdos
        logger.warning(f"[T{thread_id}] Medición anómala (>{10000} Mbps): {bandwidth_mbps:.2f} Mbps -> 0")
        result_list[thread_id] = 0
    else:
        result_list[thread_id] = bandwidth_mbps
        logger.debug(f"[T{thread_id}] OK {bandwidth_mbps:.2f} Mbps")


def medir_ancho_banda():
    # Crea hilos, sincroniza inicio con Event y suma resultados.
    # Decide 'Falla' con las mismas reglas, pero evitando cuelgues.
    global pruebas, num_fallas

    # Fin si se alcanzó el número de pruebas
    if Numerotest != 0 and pruebas >= Numerotest:
        logger.info("Pruebas finalizadas por límite configurado.")
        print("\n🚀 Pruebas finalizadas. Saliendo...")
        return "Finalizado"

    pruebas += 1
    print(f"\n📡 Prueba Nro: {pruebas}")
    logger.info(f"==== Iniciando prueba {pruebas} ====")

    start_event = threading.Event()
    results = [0.0] * NUM_THREADS
    threads = []

    # Lanzar hilos
    for i in range(NUM_THREADS):
        t = threading.Thread(target=enviar_paquetes, args=(i, results, start_event), name=f"Hilo-{i:02d}", daemon=True)
        t.start()
        threads.append(t)

    # Dar un pequeño tiempo para que todos los hilos estén listos antes de arrancar
    time.sleep(0.2)
    start_event.set()  # ¡Bandera de salida!
    logger.debug("Start event activado")

    # Esperar a que terminen (con timeout por si alguno se queda colgado)
    for t in threads:
        t.join(timeout=DURATION + 5)
        if t.is_alive():
            logger.error(f"{t.name} no finalizó a tiempo; se continuará sin él")
            # No hacemos join adicional para no bloquear

    total_bandwidth = sum(results)
    print(f"{total_bandwidth:.2f} Mbps")
    logger.info(f"Resultado total prueba {pruebas}: {total_bandwidth:.2f} Mbps (detalles por hilo: {results})")

    # Historial para promedio anterior (solo válidos numéricos)
    mediciones_validas_hist = [b for b in bandwidths if isinstance(b, (int, float, float))]

    if len(mediciones_validas_hist) > 20:
        promedio_anterior = sum(mediciones_validas_hist) / len(mediciones_validas_hist)
    else:
        promedio_anterior = total_bandwidth

    # Límites
    limite_iface_mbps = int(1000 * float(f"{interface}"))

    # Reglas de Falla
    es_falla = (
        (total_bandwidth < 1) or
        (total_bandwidth > 2 * promedio_anterior) or
        (total_bandwidth > limite_iface_mbps)
    )

    if es_falla:
        print("\n❌ Falla detectada: No se envió tráfico, salto atípico o límite de interfaz excedido.")
        logger.warning(f"Prueba {pruebas}: FALLA (total={total_bandwidth:.2f} Mbps, promedio_ant={promedio_anterior:.2f}, límite={limite_iface_mbps})")
        total_value = "Falla"
        num_fallas += 1
    else:
        print("\n📊 Resultados:")
        print(f"📤 Ancho de banda total medido: {total_bandwidth:.2f} Mbps")
        total_value = total_bandwidth

    # Guardar para gráfica y CSV
    timestamp = datetime.now().strftime("%H:%M:%S")
    times.append(timestamp)
    bandwidths.append(total_value)

    with open(CSV_FILE, mode="a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([datetime.now().strftime("%Y-%m-%d"), timestamp, total_value])

    return "En progreso"


def update(frame):
    estado = medir_ancho_banda()  # Ejecuta una prueba por iteración

    ax.clear()
    ax.axhline(y=0, linestyle="--", linewidth=1.5, label="0 Mbps")

    # Convertir fallas a 0 para graficar/promediar
    valores_numericos = [b if isinstance(b, (int, float)) else 0 for b in bandwidths]
    total_pruebas = len(bandwidths)
    promedio_total = sum(valores_numericos) / total_pruebas if total_pruebas > 0 else 0

    line, = ax.plot(times, valores_numericos, marker="o", linestyle="-", label="Ancho de Banda (Mbps)")

    # Ajuste eje Y
    valores_validos = [b for b in valores_numericos if isinstance(b, (int, float))]
    if valores_validos:
        max_bw = max(valores_validos)
        ax.set_ylim(0, max(10, max_bw * 1.2))
    else:
        ax.set_ylim(0, 10)

    # Etiquetas
    try:
        for t, bw, raw in zip(times, valores_numericos, bandwidths):
            if isinstance(raw, str) and raw == "Falla":
                ax.text(t, 1, "Falla", fontsize=10, ha="center", va="bottom", rotation=90, fontweight='bold')
            else:
                ax.text(t, bw + (max_bw * 0.05 if 'max_bw' in locals() else 0.5),
                        f"{bw:.2f} Mbps", fontsize=9, ha="center", va="bottom", rotation=90)
    except Exception as e:
        logger.debug(f"Etiqueta puntos: {e}")

    # Leyenda compacta (últimos 8 items por claridad)
    valid_handles = [mlines.Line2D([], [], marker="o", markersize=6, label=f"P{i + 1}: {bw:.2f} Mbps")
                     for i, bw in list(enumerate(valores_numericos))[-8:]]
    fail_count = sum(1 for bw in bandwidths if isinstance(bw, str) and bw == "Falla")
    fail_handle = mlines.Line2D([], [], linestyle="None", label=f"Fallas: {fail_count}")
    ax.legend(handles=[line] + valid_handles + [fail_handle], loc="upper left", fontsize=9, title="Historial")

    # Layout
    plt.subplots_adjust(left=0.05, right=0.98, top=0.90, bottom=0.18)
    if len(times) > 1:
        ax.set_xlim(times[0], times[-1])

    ax.set_title(f"Medición - {nombre_archivo} | Pruebas: {Numerotest if Numerotest else '∞'} | Fallas: {num_fallas}", fontsize=13)
    ax.set_xlabel(f"Tiempo | Prueba actual: {pruebas} | Estado: {estado or 'En progreso'} | Velocidad Promedio: {promedio_total:.2f} Mbps", fontsize=11)
    ax.set_ylabel("Ancho de Banda (Mbps)")
    ax.grid(True)
    plt.xticks(rotation=90)

    # Guardar imagen snapshot
    try:
        plt.savefig(f"{nombre_archivo}.jpg")
    except Exception as e:
        logger.debug(f"No se pudo guardar JPG: {e}")


# =============================
# Matplotlib live chart
# =============================
fig, ax = plt.subplots(figsize=(15, 7), dpi=75)

ani = animation.FuncAnimation(fig, update, interval=5000, save_count=100, cache_frame_data=False)

if __name__ == "__main__":
    try:
        plt.show(block=True)
    except KeyboardInterrupt:
        logger.info("Interrumpido por el usuario")
        pass
