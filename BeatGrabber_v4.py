import customtkinter as ctk
from tkinter import filedialog
import threading
import yt_dlp
import os
import sys
import time
import winsound 
import re 
import requests 
import warnings
import subprocess

# --- LIBRERÍAS DE ANÁLISIS ACÚSTICO ---
import librosa
import numpy as np
from mutagen.mp3 import MP3 
from mutagen.id3 import ID3, APIC, error, TIT2, TPE1, TALB, TBPM, TKEY

warnings.filterwarnings("ignore", category=UserWarning)

cancelar_descarga = False
cancelar_analisis = False

def obtener_ruta_recurso(ruta_relativa):
    try:
        ruta_base = sys._MEIPASS
    except Exception:
        ruta_base = os.path.abspath(".")
    return os.path.join(ruta_base, ruta_relativa)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

# --- FUNCIONES COMUNES ---
def limpiar_nombre_archivo(nombre):
    return re.sub(r'[\\/*?:"<>|]', "-", nombre)

# ==========================================
# PESTAÑA 1: SISTEMA DE DESCARGAS
# ==========================================
def log_mensaje(mensaje):
    def actualizar():
        caja_log.configure(state="normal")
        caja_log.insert("end", mensaje + "\n")
        caja_log.see("end") 
        caja_log.configure(state="disabled")
    ventana.after(0, actualizar)

def inyectar_metadatos(ruta_mp3, cancion_dict):
    try:
        titulo = cancion_dict.get('nombre', 'Desconocido')
        artistas = cancion_dict.get('artistas', 'Desconocido')
        album = cancion_dict.get('album', 'Single')
        
        audio = MP3(ruta_mp3, ID3=ID3)
        try: audio.add_tags()
        except error: pass 

        # Inyectar textos básicos
        audio.tags.add(TIT2(encoding=3, text=titulo))
        audio.tags.add(TPE1(encoding=3, text=artistas))
        audio.tags.add(TALB(encoding=3, text=album))

        # Buscar imagen 
        url_imagen = cancion_dict.get('cover_url')
        if not url_imagen and cancion_dict.get('raw_info'):
            url_imagen = cancion_dict['raw_info'].get('album', {}).get('images', [{}])[0].get('url')

        if url_imagen:
            respuesta_img = requests.get(url_imagen)
            if respuesta_img.status_code == 200:
                audio.tags.add(
                    APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=respuesta_img.content)
                )
        audio.save() 
    except Exception:
        pass

def seleccionar_carpeta():
    ruta_elegida = filedialog.askdirectory(title="Elige dónde guardar la música")
    if ruta_elegida:
        entrada_carpeta.delete(0, 'end')
        entrada_carpeta.insert(0, ruta_elegida)

def abrir_carpeta_destino():
    ruta = entrada_carpeta.get().strip()
    if os.path.exists(ruta):
        os.startfile(ruta)

def boton_accion():
    global cancelar_descarga
    
    if boton_descargar.cget("text") == "🛑 CANCELAR DESCARGA":
        cancelar_descarga = True
        boton_descargar.configure(text="⏳ Deteniendo...", state="disabled")
        log_mensaje("🛑 Solicitud de parada enviada...")
        return

    cancelar_descarga = False
    enlace = entrada_url.get().strip()
    carpeta = entrada_carpeta.get().strip()

    if not enlace or not carpeta:
        return

    boton_descargar.configure(text="🛑 CANCELAR DESCARGA", fg_color="red", hover_color="darkred")
    boton_abrir.pack_forget()
    caja_log.configure(state="normal")
    caja_log.delete("1.0", "end")
    caja_log.configure(state="disabled")
    
    threading.Thread(target=ejecutar_descarga, args=(enlace, carpeta)).start()

def restaurar_interfaz(mostrar_abrir=False):
    boton_descargar.configure(text="▶ INICIAR DESCARGA", fg_color=['#2CC985', '#2FA572'], hover_color=['#0C955A', '#106A43'], state="normal")
    barra_progreso.set(0)
    if mostrar_abrir:
        boton_abrir.pack(pady=5)

def ejecutar_descarga(playlist_url, ruta_descarga):
    global cancelar_descarga
    
    log_mensaje("🔗 Analizando el enlace...")
    canciones = []
    
    try:
        # ==========================================
        # RUTA 1: SPOTIFY (NAVEGADOR "ASPIRADORA")
        # ==========================================
        if "spotify.com" in playlist_url:
            log_mensaje("🟢 Spotify Detectado. Arrancando navegador fantasma...")
            log_mensaje("   (Esto tomará unos segundos la primera vez)")
            
            try:
                from selenium import webdriver
                from selenium.webdriver.chrome.service import Service
                from selenium.webdriver.chrome.options import Options
                from webdriver_manager.chrome import ChromeDriverManager
                from selenium.webdriver.common.by import By
                from selenium.webdriver.common.keys import Keys
            except ImportError:
                raise Exception("Faltan librerías. Ejecuta en terminal: pip install selenium webdriver-manager")

            # Configuración del navegador invisible
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--log-level=3") 
            chrome_options.add_argument("--mute-audio")
            
            # Instalar ChromeDriver y evitar ventana negra en Windows
            service = Service(ChromeDriverManager().install())
            if os.name == 'nt':
                service.creation_flags = subprocess.CREATE_NO_WINDOW

            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            try:
                log_mensaje("🌐 Extrayendo datos mientras hacemos Scroll (Modo Aspiradora)...")
                driver.get(playlist_url)
                time.sleep(4) 
                
                body = driver.find_element(By.TAG_NAME, 'body')
                body.send_keys(Keys.ESCAPE) 
                time.sleep(1)
                
                canciones_extraidas = {} # Diccionario para evitar duplicados
                intentos_vacios = 0
                hitos_log = 0
                
                script_extraccion = """
                let rows = document.querySelectorAll('[data-testid="tracklist-row"]');
                let result = [];
                
                rows.forEach(row => {
                    let links = row.querySelectorAll('a');
                    let title = 'Desconocido';
                    let artists = [];
                    let album = 'Single';
                    
                    links.forEach(link => {
                        let href = link.getAttribute('href');
                        if (href && href.includes('/track/')) {
                            title = link.innerText;
                        } else if (href && href.includes('/artist/')) {
                            artists.push(link.innerText);
                        } else if (href && href.includes('/album/')) {
                            album = link.innerText;
                        }
                    });
                    
                    if (title === 'Desconocido') {
                        let divText = row.querySelector('div[dir="auto"]');
                        if (divText) title = divText.innerText;
                    }
                    
                    if (artists.length === 0) artists.push('Desconocido');
                    
                    let img = row.querySelector('img');
                    let cover_url = img ? img.getAttribute('src') : null;
                    
                    result.push({
                        'nombre': title,
                        'artistas': artists.join(', '),
                        'album': album,
                        'cover_url': cover_url,
                        'raw_info': null
                    });
                });
                
                return result;
                """
                
                # Bucle de scroll infinito con extracción en vivo
                while intentos_vacios < 6:
                    if cancelar_descarga: break
                    
                    # 1. Extraer lo que hay en pantalla AHORA MISMO
                    pistas_visibles = driver.execute_script(script_extraccion)
                    nuevas_en_esta_pasada = False
                    
                    for track in pistas_visibles:
                        if track['nombre'] != 'Desconocido' and track['nombre'].strip() != '':
                            # Creamos una ID única juntando nombre y artista para que no se repitan
                            id_unico = f"{track['nombre']} - {track['artistas']}"
                            if id_unico not in canciones_extraidas:
                                canciones_extraidas[id_unico] = track
                                nuevas_en_esta_pasada = True
                                
                    if nuevas_en_esta_pasada:
                        intentos_vacios = 0
                        # Imprimir un aviso en el log cada 100 canciones
                        if len(canciones_extraidas) >= hitos_log + 100:
                            hitos_log += 100
                            log_mensaje(f"   ⏳ Llevamos {len(canciones_extraidas)} pistas extraídas...")
                    else:
                        intentos_vacios += 1 # Si hemos bajado y no hay canciones nuevas, estamos llegando al fondo
                        
                    # 2. Hacer scroll para cargar las siguientes
                    body.send_keys(Keys.PAGE_DOWN)
                    time.sleep(0.6) 
                
                if cancelar_descarga:
                    driver.quit()
                    restaurar_interfaz()
                    return

                # Convertimos el diccionario sin duplicados en una lista normal
                canciones = list(canciones_extraidas.values())
                
                log_mensaje(f"✅ ¡Fin de la lista! Total real extraído: {len(canciones)} pistas.")
                        
                if variable_subcarpeta.get() and len(canciones) > 0:
                    nombre_carpeta_lista = limpiar_nombre_archivo("Spotify Phantom Download")
                    ruta_descarga = os.path.join(ruta_descarga, nombre_carpeta_lista)
                    if not os.path.exists(ruta_descarga):
                        os.makedirs(ruta_descarga)
                    log_mensaje(f"📁 Se agrupará en: {nombre_carpeta_lista}")
                
            except Exception as internal_e:
                raise Exception(f"Fallo en el navegador fantasma: {str(internal_e)}")
            finally:
                driver.quit() 

        # ==========================================
        # RUTA 2: YOUTUBE / DEEZER (YT-DLP)
        # ==========================================
        elif "youtube.com" in playlist_url or "youtu.be" in playlist_url or "deezer.com" in playlist_url:
            log_mensaje("🔴 Plataforma Libre. Usando yt-dlp...")
            opciones_extraccion = {'extract_flat': 'in_playlist', 'quiet': True, 'no_warnings': True}
            
            if not os.path.exists(ruta_descarga):
                os.makedirs(ruta_descarga)
                
            with yt_dlp.YoutubeDL(opciones_extraccion) as ydl:
                info_lista = ydl.extract_info(playlist_url, download=False)
                
                if not info_lista:
                    raise Exception("No se pudo extraer información del enlace.")
                
                if variable_subcarpeta.get() and 'title' in info_lista:
                    nombre_carpeta_lista = limpiar_nombre_archivo(info_lista['title'])
                    ruta_descarga = os.path.join(ruta_descarga, nombre_carpeta_lista)
                    if not os.path.exists(ruta_descarga):
                        os.makedirs(ruta_descarga)
                    log_mensaje(f"📁 Se agrupará en: {nombre_carpeta_lista}")
                
                if 'entries' in info_lista:
                    for entry in info_lista['entries']:
                        if entry and entry.get('title'):
                            canciones.append({
                                'nombre': entry.get('title'),
                                'artistas': entry.get('artist') or entry.get('uploader') or entry.get('channel') or "Desconocido",
                                'album': info_lista.get('title', 'Single'),
                                'raw_info': None
                            })
                else:
                    canciones.append({
                        'nombre': info_lista.get('title', 'Desconocido'),
                        'artistas': info_lista.get('artist') or info_lista.get('uploader') or info_lista.get('channel') or "Desconocido",
                        'album': "Single",
                        'raw_info': None
                    })
        else:
            log_mensaje("❌ Error: Enlace no soportado. Usa Spotify, YouTube o Deezer.")
            restaurar_interfaz()
            return

    except Exception as e:
        log_mensaje(f"❌ Error de extracción: {str(e)}")
        restaurar_interfaz()
        return

    total_canciones = len(canciones)
    if total_canciones == 0:
        log_mensaje("⚠️ No se encontraron canciones válidas.")
        restaurar_interfaz()
        return

    log_mensaje(f"🎶 Procediendo a descargar {total_canciones} pistas...")
    formato_elegido = variable_formato.get().lower()
    contador = 0
    fallos = 0

    # --- BUCLE DE DESCARGA ---
    for cancion in canciones:
        if cancelar_descarga: break
        contador += 1
        barra_progreso.set(contador / total_canciones)
        
        nombre_cancion = cancion['nombre']
        artistas = cancion['artistas']
        nombre_album = cancion['album']
        
        nombre_limpio = limpiar_nombre_archivo(f"{nombre_cancion} - {artistas} - {nombre_album}")
        ruta_final = f"{ruta_descarga}/{nombre_limpio}.{formato_elegido}"
        
        log_mensaje(f"\n[{contador}/{total_canciones}] {nombre_cancion}...")
        
        if os.path.exists(ruta_final):
            log_mensaje("   ⏭️ Ya existe en la carpeta. Saltando...")
            continue
        
        opciones_descarga = {
            'format': 'bestaudio/best',
            'postprocessors': [
                {'key': 'FFmpegExtractAudio', 'preferredcodec': formato_elegido, 'preferredquality': '320'},
                {'key': 'EmbedThumbnail'}
            ],
            'writethumbnail': True,
            'outtmpl': f'{ruta_descarga}/{nombre_limpio}.%(ext)s',
            'quiet': True, 
            'no_warnings': True, 
            'windowsfilenames': True,
        }
        
        ydl = yt_dlp.YoutubeDL(opciones_descarga)
        exito = False
        
        for intento in range(3):
            if cancelar_descarga: break
            if intento == 0: busqueda = f"{artistas} - {nombre_cancion} lyrics"
            elif intento == 1: busqueda = f"{artistas} - {nombre_cancion} audio"
            elif intento == 2: busqueda = f"{artistas} - {nombre_cancion} oficial"
                
            try:
                if ydl.download([f"ytsearch1:{busqueda}"]) == 0:
                    exito = True
                    break 
            except Exception:
                time.sleep(1)
                
        if exito and not cancelar_descarga:
            inyectar_metadatos(ruta_final, cancion) 
            log_mensaje("   ✅ ¡Lista para pinchar!")
                
        if not exito and not cancelar_descarga:
            log_mensaje("   ❌ Imposible descargar.")
            fallos += 1

    if not cancelar_descarga:
        winsound.MessageBeep(winsound.MB_ICONASTERISK) 
        if fallos > 0:
            log_mensaje(f"\n✅ Terminado. Fallaron: {fallos}")
        else:
            log_mensaje("\n🎉 ¡DESCARGA COMPLETADA AL 100%!")
        restaurar_interfaz(mostrar_abrir=True)


# ==========================================
# PESTAÑA 2: UTILIDADES DJ (Generador + Analizador)
# ==========================================
def log_utilidades_msg(mensaje):
    def actualizar():
        caja_log_dj.configure(state="normal")
        caja_log_dj.insert("end", mensaje + "\n")
        caja_log_dj.see("end") 
        caja_log_dj.configure(state="disabled")
    ventana.after(0, actualizar)

def seleccionar_carpeta_utilidades():
    ruta_elegida = filedialog.askdirectory(title="Elige la carpeta de música a procesar")
    if ruta_elegida:
        entrada_carpeta_utilidades.delete(0, 'end')
        entrada_carpeta_utilidades.insert(0, ruta_elegida)

def generar_tracklist():
    carpeta = entrada_carpeta_utilidades.get().strip()
    if not carpeta or not os.path.exists(carpeta): return
        
    try:
        archivos = os.listdir(carpeta)
        canciones = sorted([f for f in archivos if f.lower().endswith(('.mp3', '.wav', '.flac', '.m4a'))])
        if not canciones: return
            
        ruta_txt = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="Tracklist.txt", title="Guardar Tracklist")
        if not ruta_txt: return
        
        with open(ruta_txt, "w", encoding="utf-8") as f:
            for cancion in canciones:
                f.write(f"{os.path.splitext(cancion)[0]}\n")
                
        os.startfile(ruta_txt)
        log_utilidades_msg("📄 Tracklist generado correctamente.")
    except Exception:
        pass

def matematicas_acusticas(ruta_archivo):
    try:
        y, sr = librosa.load(ruta_archivo, sr=22050)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm_calculado = str(round(tempo[0] if isinstance(tempo, (list, np.ndarray)) else tempo))
        
        chroma = librosa.feature.chroma_stft(y=y, sr=sr)
        chroma_sum = np.sum(chroma, axis=1)
        
        pitches = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        maj_profile = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
        min_profile = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

        maj_corrs = [np.corrcoef(chroma_sum, np.roll(maj_profile, i))[0, 1] for i in range(12)]
        min_corrs = [np.corrcoef(chroma_sum, np.roll(min_profile, i))[0, 1] for i in range(12)]

        if max(maj_corrs) > max(min_corrs):
            key_calculada = f"{pitches[np.argmax(maj_corrs)]}m"
        else:
            key_calculada = f"{pitches[np.argmax(min_corrs)]}m"

        return bpm_calculado, key_calculada
    except Exception:
        return None, None

def inyectar_analisis_id3(ruta_archivo, bpm, key):
    try:
        audio = MP3(ruta_archivo, ID3=ID3)
        try: audio.add_tags()
        except error: pass
            
        audio.tags.add(TBPM(encoding=3, text=bpm))
        audio.tags.add(TKEY(encoding=3, text=key))
        audio.save()
    except Exception:
        pass

def proceso_analisis_carpeta():
    global cancelar_analisis
    carpeta = entrada_carpeta_utilidades.get().strip()
    if not carpeta or not os.path.exists(carpeta): return
    
    archivos = sorted([f for f in os.listdir(carpeta) if f.lower().endswith('.mp3')])
    total = len(archivos)
    
    if total == 0:
        log_utilidades_msg("⚠️ No hay archivos MP3 para analizar.")
        restaurar_botones_dj()
        return

    log_utilidades_msg(f"🎧 Iniciando análisis acústico de {total} pistas...")
    
    contador = 0
    for archivo in archivos:
        if cancelar_analisis: break
        contador += 1
        ruta_completa = os.path.join(carpeta, archivo)
        
        log_utilidades_msg(f"[{contador}/{total}] Analizando: {archivo}...")
        
        bpm, key = matematicas_acusticas(ruta_completa)
        if bpm and key and not cancelar_analisis:
            inyectar_analisis_id3(ruta_completa, bpm, key)
            log_utilidades_msg(f"   ✅ Guardado -> BPM: {bpm} | Key: {key}")
        else:
            if not cancelar_analisis:
                log_utilidades_msg("   ❌ Error leyendo acústica.")
                
    log_utilidades_msg("\n🎉 Análisis finalizado.")
    winsound.MessageBeep(winsound.MB_ICONASTERISK)
    restaurar_botones_dj()

def boton_iniciar_analisis():
    global cancelar_analisis
    if boton_analizar.cget("text") == "🛑 CANCELAR ANÁLISIS":
        cancelar_analisis = True
        boton_analizar.configure(text="⏳ Deteniendo...", state="disabled")
        return
        
    cancelar_analisis = False
    caja_log_dj.configure(state="normal")
    caja_log_dj.delete("1.0", "end")
    caja_log_dj.configure(state="disabled")
    
    boton_analizar.configure(text="🛑 CANCELAR ANÁLISIS", fg_color="red", hover_color="darkred")
    threading.Thread(target=proceso_analisis_carpeta).start()

def restaurar_botones_dj():
    boton_analizar.configure(text="🔬 ANALIZAR BPM Y KEY", fg_color=['#3B8ED0', '#1F6AA5'], hover_color=['#36719F', '#144870'], state="normal")

# ==========================================
# INTERFAZ GRÁFICA PRINCIPAL
# ==========================================
ventana = ctk.CTk()
ventana.title("BeatGrabber Pro v4.0 (Suite Edition)")
try: ventana.iconbitmap(obtener_ruta_recurso("icono.ico")) 
except: pass 
ventana.geometry("680x820") 
ventana.resizable(False, False)

marco_superior = ctk.CTkFrame(ventana, fg_color="transparent")
marco_superior.pack(fill="x", padx=20, pady=(15, 5))
ctk.CTkLabel(marco_superior, text="💿 BeatGrabber v4.0", font=("Helvetica", 24, "bold")).pack(side="left", padx=20)

pestañas = ctk.CTkTabview(ventana, width=640)
pestañas.pack(padx=20, pady=5, fill="both", expand=True)

tab_descargas = pestañas.add("📥 Descargas")
tab_utilidades = pestañas.add("⚙️ Utilidades DJ")

# --- DISEÑO: PESTAÑA 1 ---
ctk.CTkLabel(tab_descargas, text="Enlace (Spotify / YouTube / Deezer):", font=("Helvetica", 14)).pack(anchor="w", padx=30)
entrada_url = ctk.CTkEntry(tab_descargas, width=540, placeholder_text="Pega aquí el enlace de la playlist o álbum")
entrada_url.pack(pady=5)

marco_opciones = ctk.CTkFrame(tab_descargas, fg_color="transparent")
marco_opciones.pack(fill="x", padx=30, pady=(5, 5))
ctk.CTkLabel(marco_opciones, text="Carpeta base:", font=("Helvetica", 14)).pack(side="left")
entrada_carpeta = ctk.CTkEntry(marco_opciones, width=280)
entrada_carpeta.pack(side="left", padx=10)
ctk.CTkButton(marco_opciones, text="Examinar...", width=90, command=seleccionar_carpeta).pack(side="left")

variable_subcarpeta = ctk.BooleanVar(value=True) 
ctk.CTkCheckBox(tab_descargas, text="📁 Crear subcarpeta automática", variable=variable_subcarpeta).pack(anchor="w", padx=30, pady=5)

marco_formato = ctk.CTkFrame(tab_descargas, fg_color="transparent")
marco_formato.pack(fill="x", padx=30, pady=(5, 10))
ctk.CTkLabel(marco_formato, text="Formato de audio:", font=("Helvetica", 14)).pack(side="left")
variable_formato = ctk.StringVar(value="MP3")
ctk.CTkOptionMenu(marco_formato, values=["MP3", "WAV"], variable=variable_formato, width=100).pack(side="left", padx=10)

caja_log = ctk.CTkTextbox(tab_descargas, width=540, height=160, font=("Consolas", 12), fg_color="black", text_color="#00FF00") 
caja_log.pack(pady=5)

barra_progreso = ctk.CTkProgressBar(tab_descargas, width=540)
barra_progreso.set(0)
barra_progreso.pack(pady=10)

boton_descargar = ctk.CTkButton(tab_descargas, text="▶ INICIAR DESCARGA", font=("Helvetica", 16, "bold"), height=50, command=boton_accion)
boton_descargar.pack(pady=5)
boton_abrir = ctk.CTkButton(tab_descargas, text="📂 Abrir Carpeta", font=("Helvetica", 14), fg_color="gray30", hover_color="gray40", command=abrir_carpeta_destino)

# --- DISEÑO: PESTAÑA 2 ---
marco_sel_utilidades = ctk.CTkFrame(tab_utilidades, fg_color="transparent")
marco_sel_utilidades.pack(fill="x", padx=30, pady=(15, 0))
ctk.CTkLabel(marco_sel_utilidades, text="1. Selecciona la carpeta de trabajo:", font=("Helvetica", 14, "bold")).pack(anchor="w")
marco_input_util = ctk.CTkFrame(marco_sel_utilidades, fg_color="transparent")
marco_input_util.pack(fill="x", pady=5)
entrada_carpeta_utilidades = ctk.CTkEntry(marco_input_util, width=430, placeholder_text="Ruta de tu música...")
entrada_carpeta_utilidades.pack(side="left", padx=(0, 10))
ctk.CTkButton(marco_input_util, text="Examinar...", width=90, command=seleccionar_carpeta_utilidades).pack(side="left")

ctk.CTkFrame(tab_utilidades, height=2, fg_color="gray30").pack(fill="x", padx=30, pady=20)

marco_herramientas = ctk.CTkFrame(tab_utilidades, fg_color="transparent")
marco_herramientas.pack(fill="x", padx=30)

marco_tracklist = ctk.CTkFrame(marco_herramientas, fg_color="transparent")
marco_tracklist.pack(side="left", fill="both", expand=True)
ctk.CTkLabel(marco_tracklist, text="📄 Tracklist", font=("Helvetica", 16, "bold")).pack(pady=(0, 5))
ctk.CTkLabel(marco_tracklist, text="Genera un archivo de\ntexto con los nombres.", text_color="gray").pack(pady=(0, 10))
ctk.CTkButton(marco_tracklist, text="Generar TXT", command=generar_tracklist).pack()

marco_bpm = ctk.CTkFrame(marco_herramientas, fg_color="transparent")
marco_bpm.pack(side="right", fill="both", expand=True)
ctk.CTkLabel(marco_bpm, text="🔬 Analizador Acústico", font=("Helvetica", 16, "bold")).pack(pady=(0, 5))
ctk.CTkLabel(marco_bpm, text="Calcula y guarda BPM y Key\nen los metadatos del MP3.", text_color="gray").pack(pady=(0, 10))
boton_analizar = ctk.CTkButton(marco_bpm, text="🔬 ANALIZAR BPM Y KEY", fg_color=['#3B8ED0', '#1F6AA5'], hover_color=['#36719F', '#144870'], command=boton_iniciar_analisis)
boton_analizar.pack()

caja_log_dj = ctk.CTkTextbox(tab_utilidades, width=540, height=200, font=("Consolas", 12), fg_color="black", text_color="#1DB954") 
caja_log_dj.pack(pady=25)
caja_log_dj.insert("end", ">> Módulo DJ cargado. Selecciona una carpeta arriba.\n")
caja_log_dj.configure(state="disabled")

ventana.mainloop()