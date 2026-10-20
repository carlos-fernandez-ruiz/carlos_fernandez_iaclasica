"""
Cliente de voz para Windows: micrófono → Dialogflow → altavoz.
Dialogflow transcribe, detecta la intención y genera el audio en una llamada.

Requiere GOOGLE_APPLICATION_CREDENTIALS, DIALOGFLOW_PROJECT_ID y una voz
es-ES activada en el agente. Consulta la instalación en el README principal.

Enter inicia y termina la grabación. También puedes escribir una frase.
Con q o una despedida termina la conversación.
"""

import html
import io
import os
import re
import statistics
import sys
import time
import uuid
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
from dotenv import load_dotenv
from google.api_core.exceptions import GoogleAPICallError, RetryError
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import dialogflow

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

PROJECT_ID = os.environ.get("DIALOGFLOW_PROJECT_ID", "")
IDIOMA = "es"
FS = 16000              # Dialogflow espera 16 kHz para LINEAR_16
LATENCIA_MAXIMA = 5.0   # segundos por turno antes de mostrar un aviso
MARGEN_FINAL_MS = 500   # se sigue grabando un poco tras pulsar Enter
TIEMPO_MAXIMO = 15      # segundos de espera máxima

# Ayuda al reconocimiento de nombres de clases en inglés.
PISTAS = dialogflow.SpeechContext(
    phrases=["yoga", "pilates", "spinning", "zumba", "body pump", "HIIT",
             "crossfit", "ciclo indoor", "DNI"],
    boost=10,
)

SALIDA = dialogflow.OutputAudioConfig(
    audio_encoding=dialogflow.OutputAudioEncoding.OUTPUT_AUDIO_ENCODING_LINEAR_16
)

# La misma sesión conserva los datos entre turnos.
SESSION_ID = str(uuid.uuid4())


# Audio

def grabar() -> bytes:
    """Graba desde ahora hasta que se pulsa Enter (pulsar para hablar)."""
    bloques = []

    def guardar(datos, frames, tiempo, estado):
        bloques.append(datos.copy())

    with sd.InputStream(samplerate=FS, channels=1, dtype="int16", callback=guardar):
        input("  Grabando... (Enter para terminar)")
        # Este margen evita cortar la última palabra al pulsar Enter.
        sd.sleep(MARGEN_FINAL_MS)
    return np.concatenate(bloques).tobytes() if bloques else b""


def reproducir(wav_bytes: bytes) -> None:
    """El audio LINEAR_16 de Dialogflow ya es un WAV completo (cabecera RIFF)."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        muestras = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        tasa = w.getframerate()
    sd.play(muestras, tasa)
    sd.wait()


# Dialogflow

def consultar(clientes, sesion: str, audio: bytes | None = None, texto: str | None = None):
    if audio is not None:
        entrada = dialogflow.QueryInput(audio_config=dialogflow.InputAudioConfig(
            audio_encoding=dialogflow.AudioEncoding.AUDIO_ENCODING_LINEAR_16,
            language_code=IDIOMA,
            sample_rate_hertz=FS,
            speech_contexts=[PISTAS],
        ))
    else:
        entrada = dialogflow.QueryInput(text=dialogflow.TextInput(text=texto, language_code=IDIOMA))

    peticion = {"session": sesion, "query_input": entrada, "output_audio_config": SALIDA}
    if audio is not None:
        peticion["input_audio"] = audio
    return clientes.detect_intent(request=peticion, timeout=TIEMPO_MAXIMO)


def sin_ssml(texto: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", texto))


def mostrar(respuesta, latencia: float) -> None:
    r = respuesta.query_result
    # query_text contiene la transcripción del audio.
    print(f"  Has dicho  : {r.query_text or '(no se ha reconocido nada)'}")
    print(f"  Intención  : {r.intent.display_name} ({r.intent_detection_confidence:.2f})")
    print(f"  Parámetros : {dict(r.parameters)}")
    print(f"  Responde   : {sin_ssml(r.fulfillment_text)}")
    if respuesta.webhook_status.code:
        print(f"  Webhook    : ERROR {respuesta.webhook_status.code} {respuesta.webhook_status.message}")
    aviso = "" if latencia < LATENCIA_MAXIMA else f"  <-- supera {LATENCIA_MAXIMA:.0f} s"
    print(f"  Latencia   : {latencia:.2f} s{aviso}")


def resumen(latencias: list[float]) -> None:
    if not latencias:
        return
    lentos = sum(1 for t in latencias if t >= LATENCIA_MAXIMA)
    print(f"\n{len(latencias)} turnos. Latencia mediana {statistics.median(latencias):.2f} s, "
          f"máxima {max(latencias):.2f} s, {lentos} por encima de {LATENCIA_MAXIMA:.0f} s.")


# Bucle de conversación

def main() -> None:
    if not PROJECT_ID:
        sys.exit("Falta DIALOGFLOW_PROJECT_ID en el .env de la raíz del repositorio.")
    try:
        clientes = dialogflow.SessionsClient()
    except DefaultCredentialsError:
        sys.exit("No encuentro la clave: define GOOGLE_APPLICATION_CREDENTIALS con la ruta al JSON.")
    sesion = clientes.session_path(PROJECT_ID, SESSION_ID)

    print("=" * 60)
    print("Cliente de voz del Gimnasio Atlas")
    print(f"Proyecto : {PROJECT_ID}")
    print(f"Sesión   : {SESSION_ID}")
    print("Enter para hablar (y Enter para terminar), una frase para")
    print("enviarla como texto, 'q' para salir.")
    print("=" * 60)

    latencias = []
    while True:
        orden = input("\n> ").strip()
        if orden.lower() == "q":
            break

        if orden:
            audio, texto = None, orden
        else:
            audio, texto = grabar(), None
            if len(audio) < FS * 2 * 0.3:  # menos de 0,3 s (2 bytes por muestra)
                print("  Grabación demasiado corta, prueba otra vez.")
                continue
            print(f"  Grabados {len(audio) / (FS * 2):.1f} s. Enviando a Dialogflow...")

        # Mide la espera hasta recibir la respuesta, sin contar su reproducción.
        inicio = time.perf_counter()
        try:
            respuesta = consultar(clientes, sesion, audio=audio, texto=texto)
        except (GoogleAPICallError, RetryError) as e:  # incluye superar TIEMPO_MAXIMO
            print(f"  Error de Dialogflow: {e}")
            continue
        latencia = time.perf_counter() - inicio
        latencias.append(latencia)

        mostrar(respuesta, latencia)
        if respuesta.output_audio:
            reproducir(respuesta.output_audio)
        else:
            print("  (Sin audio: ¿está activado Text to Speech en el agente?)")

        if respuesta.query_result.intent.display_name == "despedida":
            break

    resumen(latencias)


if __name__ == "__main__":
    main()
