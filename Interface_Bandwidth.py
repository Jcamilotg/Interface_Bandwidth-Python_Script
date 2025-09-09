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
velocidad = float(input("Ingrese la opción deseada: \t"))

try:

    if velocidad == 1:
        interface = 0.4
        print("[1] Wi-Fi 2.4GHz")
    if velocidad == 2:
        interface = 2
        print("[2] Wi-Fi 5GHz")
    if velocidad == 3:
        interface = 3
        print("[3] Wi-Fi 6GHz")
    if velocidad == 4:
        interface = 7
        print("[4] Wi-Fi 7")
    if velocidad == 5:
        interface = 1
        print("[5] Ethernet 1 Gbps")
    if velocidad == 6:
        interface = 2.5
        print("[6] Ethernet 2.5 Gbps")
    if velocidad == 7:
        interface = 5
        print("[7] Ethernet 5 Gbps")
    if velocidad == 8:
        interface = 10
        print("[8] Ethernet 10 Gbps")

except:
    print("Error")
    os.system("python3 Interface_Bandwidth.py")


# Configuración
DEST_IP = "192.168.75.254"
PORT = 5001  # Puerto de destino
PACKET_SIZE = 65000  # Tamaño del paquete UDP (65 KB)
DURATION = 15  # Duración en segundos
NUM_THREADS = 10  # Cantidad de hilos para saturar la red

nombre_archivo = input("\nIngrese Nombre del archivo Log a guardar: \t")
Numerotest = int(input("\nIngrese número de pruebas, si quiere infinitos agregue '0': \t"))
#velocidad_interfaz = int(input("\nIngrese velocidad de la interfaz en Gigas, solo enteros, ejemplo 1, 2, 3: \t"))
pruebas = 0

mediciones = []
# Archivo CSV para guardar historial
CSV_FILE = f"{nombre_archivo}.csv"

# Si el archivo no existe, crear y escribir el encabezado
if not open(CSV_FILE, "a").tell():
    with open(CSV_FILE, mode="w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["Fecha", "Hora", "Ancho de Banda (Mbps)"])  # Encabezados

# Configuración de la gráfica
MAX_POINTS = 5000  # Máximo de puntos en la gráfica
times = deque(maxlen=MAX_POINTS)  # Almacena tiempos
bandwidths = deque(maxlen=MAX_POINTS)  # Almacena mediciones

#sinconizar hilos para que envien al mismo tiempo
BARRIER = threading.Barrier(NUM_THREADS)
def enviar_paquetes(thread_id, result_list):
    time.sleep(5)
    """
    Función para enviar paquetes UDP desde un hilo.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # 🔹 **Reducir buffer de envío y recepción para evitar acumulación**

    BARRIER.wait()  # 🔹 Asegura que todos los hilos comiencen al mismo tiempo

    start_time = time.time()
    bytes_sent = 0

    while time.time() - start_time < DURATION:
        try:
            sock.sendto(b'X' * PACKET_SIZE, (DEST_IP, PORT))
            bytes_sent += PACKET_SIZE
        except socket.error:
            result_list[thread_id] = 0  # 🔹 Si falla la interfaz, registrar 0 Mbps
            return

    elapsed_time = time.time() - start_time

    # **🔹 Verificar si la interfaz está desconectada o si el tiempo es demasiado corto**
    if bytes_sent == 0 or elapsed_time < 1:
        result_list[thread_id] = 0  # 🔹 Registrar como falla
        return

    # **🔹 Calcular ancho de banda (Mbps)**
    bandwidth_mbps = (bytes_sent * 8) / (elapsed_time * 1_000_000)

    # **🔹 Filtrar valores anormales**
    if bandwidth_mbps > 10000:  # Ajustable según la red
        result_list[thread_id] = 0  # 🔹 Registrar como error
    else:
        result_list[thread_id] = bandwidth_mbps  # 🔹 Guardar el resultado válido

num_fallas = 0
def medir_ancho_banda():
    """
    Crea múltiples hilos para enviar tráfico UDP simultáneamente.
    """
    global pruebas
    global num_fallas
    if Numerotest != 0 and pruebas >= Numerotest:
        print("\n🚀 Pruebas finalizadas. Saliendo...")
        return

    pruebas += 1
    print(f"\n📡 Prueba Nro: {pruebas}")

    threads = []
    results = [0] * NUM_THREADS  # Lista para almacenar resultados de cada hilo

    for i in range(NUM_THREADS):
        thread = threading.Thread(target=enviar_paquetes, args=(i, results))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()  # Esperar a que todos los hilos terminen

    # Calcular ancho de banda total sumando lo de todos los hilos
    total_bandwidth = sum(results)
    print(f"{total_bandwidth:.2f} Mbps")

    # 🔹 **Filtrar solo valores numéricos (descartar "Falla")**
    mediciones_validas = [b for b in bandwidths if isinstance(b, (int, float))]

    #mediciones.append(total_bandwidth)
    # 🔹 **Cálculo del promedio de las mediciones anteriores**
    if len(mediciones_validas) > 20:  # Asegurar que haya suficiente historial
        promedio_anterior = sum(mediciones_validas) / len(mediciones_validas)
    else:
        promedio_anterior = total_bandwidth  # Evita dividir por 0 en las primeras pruebas
        #print(promedio_anterior)


        # **🔹 Mostrar estado correcto**
    if total_bandwidth < 1 or total_bandwidth > 2 * promedio_anterior or total_bandwidth > int(1000 * float(f"{interface}")):
        print("\n❌ Falla detectada: No se envió tráfico o la interfaz está desconectada.")
        total_bandwidth = "Falla"  # Marcar como fallo en el CSV
        num_fallas += 1
    else:
        print(f"\n📊 Resultados:")
        print(f"📤 Ancho de banda total medido: {total_bandwidth:.2f} Mbps")

        # Guardar datos en listas para graficar
    timestamp = datetime.now().strftime("%H:%M:%S")
    times.append(timestamp)
    bandwidths.append(total_bandwidth)

    # Guardar en CSV
    with open(CSV_FILE, mode="a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([datetime.now().strftime("%Y-%m-%d"), timestamp, total_bandwidth])

    return "En progreso"


def update(frame):
    medir_ancho_banda()  # Ejecutar prueba en cada iteración

    ax.clear()
    ax.axhline(y=0, color="red", linestyle="--", linewidth=1.5, label="0 Mbps")

    # Convertir fallas en 0 y calcular el promedio correctamente
    valores_numericos = [b if isinstance(b, (int, float)) else 0 for b in bandwidths]
    total_pruebas = len(bandwidths)  # Contar TODAS las pruebas (válidas y fallas)
    promedio_total = sum(valores_numericos) / total_pruebas if total_pruebas > 0 else 0

    line, = ax.plot(times, [b if isinstance(b, (int, float)) else 0 for b in bandwidths],
                    marker="o", linestyle="-", color="b", label="Ancho de Banda (Mbps)")

    # Ajuste dinámico del eje Y
    valores_validos = [b for b in bandwidths if isinstance(b, (int, float))]
    if valores_validos:
        max_bw = max(valores_validos)
        ax.set_ylim(0, max_bw * 1.2)  # Asegurar que haya suficiente espacio arriba
    else:
        ax.set_ylim(0, 10)  # Si solo hay fallas, mantener un pequeño rango visible

    # Etiquetar cada punto
    for i, (t, bw) in enumerate(zip(times, bandwidths)):
        if isinstance(bw, str) and bw == "Falla":
            ax.text(t, 1, "Falla", fontsize=10, color="red", ha="center", va="bottom", rotation=90, fontweight='bold')
        else:
            ax.text(t, bw + (max_bw * 0.05), f"{bw:.2f} Mbps", fontsize=10, color="green", ha="center", va="bottom", rotation=90)
        # 🔹 **Leyenda mejorada**
        # Crear handles para las pruebas válidas
    valid_handles = [mlines.Line2D([], [], color="white", marker="o", markersize=8, label=f"Prueba {i + 1}: {bw:.2f} Mbps")
                    for i, bw in enumerate(bandwidths) if isinstance(bw, (int, float))]

    # Crear handles para las fallas (rojo)
    fail_handles = [mlines.Line2D([], [], color="red", marker="o", markersize=8, label=f"Prueba {i + 1}: Falla")
                    for i, bw in enumerate(bandwidths) if isinstance(bw, str) and bw == "Falla"]

    # Agregar ambas partes a la leyenda
    ax.legend(handles=[line] + valid_handles[-5:] + fail_handles[-30:], loc="upper left", fontsize=10,
              title="Historial de Mediciones")

    # 🔹 **Actualizar la leyenda con los valores recientes**
    #legend_labels = [f"Prueba {i + 1}: {'Falla' if isinstance(bw, str) else f'{bw:.2f} Mbps'}" for i, bw in enumerate(bandwidths)]

    # Últimos 5 elementos en la leyenda
    #legend_proxies = [plt.Line2D([0], [0], color="white", marker="o", markersize=8, label=label) for label in legend_labels[-200:]]

    #ax.legend(handles=[line] + legend_proxies, loc="upper left", fontsize=10, title="Historial de Mediciones")
    # 🔹 **Ajustar el espacio de la gráfica**
    plt.subplots_adjust(left=0.05, right=0.95, top=0.90, bottom=0.15)  # Reduce márgenes generales

    # Ajustar el rango del eje X
    if len(times) > 1:
        ax.set_xlim(times[0], times[-1])

    ax.set_title(f"Medición de Ancho de Banda - Nombre: {nombre_archivo} | Nro de Pruebas: {Numerotest} | Nro Fallas: {num_fallas}", fontsize=14, color="red")
    ax.set_xlabel(f"Tiempo | Prueba Nro: {pruebas} | Estado: {'En progreso' if pruebas < Numerotest else 'Finalizado'} | Velocidad Promedio: {promedio_total:.2f} Mbps",
                  fontsize=15, color="red")
    ax.set_ylabel("Ancho de Banda (Mbps)", fontsize=12)
    ax.grid(True)
    plt.xticks(rotation=90)

    plt.savefig(f"{nombre_archivo}.jpg")
    # 🔹 **Guardar la imagen cuando finalicen todas las pruebas**


fig, ax = plt.subplots(figsize=(15, 7), dpi=75)

# Iniciar animación
ani = animation.FuncAnimation(fig, update, interval=5000, save_count=100, cache_frame_data=False)
plt.show(block=True)  # Mantiene la ventana abierta
