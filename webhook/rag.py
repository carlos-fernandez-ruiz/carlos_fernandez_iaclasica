"""
Responde preguntas con el texto de data/documentos.json.
Los cuatro documentos caben en cada consulta. Si no contienen la respuesta,
el modelo devuelve NO_ENCONTRADO. Requiere GOOGLE_API_KEY en el .env.
"""

import json
import os
import time
from pathlib import Path

from google import genai
from google.genai import errors, types

RUTA_DOCUMENTOS = Path(__file__).resolve().parent.parent / "data" / "documentos.json"

# Modelo elegido por su rapidez en las pruebas.
MODELO = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
# El límite se aplica a cada operación de red, no al tiempo total de la consulta.
TIEMPO_MAXIMO_MS = 3500
CENTINELA = "NO_ENCONTRADO"

MENSAJE_ERROR = "Ahora mismo no puedo consultar la normativa del gimnasio. Pregúntalo en recepción, por favor."


def cargar_documentos() -> dict[str, str]:
    """Lee el texto del OCR al arrancar, sin volver a procesar las imágenes."""
    if not RUTA_DOCUMENTOS.exists():
        return {}
    datos = json.loads(RUTA_DOCUMENTOS.read_text(encoding="utf-8"))
    return {d["documento"]: d["texto"] for d in datos}


DOCUMENTOS = cargar_documentos()
CONTEXTO = "\n\n".join(f"=== {nombre} ===\n{texto}" for nombre, texto in DOCUMENTOS.items())

INSTRUCCIONES = """Eres el asistente telefónico del Gimnasio Atlas.
Respondes en español, en dos frases como mucho y sin listas ni formato, porque
tu respuesta se va a convertir en voz. Solo usas la información de los
documentos que te dan: nunca usas conocimiento propio ni deduces precios,
horarios o normas que no estén escritos."""

PLANTILLA = """DOCUMENTOS (texto extraído por OCR, puede tener pequeños errores de lectura):
{contexto}

PREGUNTA: {pregunta}

Responde usando UNICAMENTE los DOCUMENTOS. Si no contienen la respuesta, o solo
contienen algo parecido pero no lo que se pregunta, responde exactamente
NO_ENCONTRADO y nada más."""

# Prueba las dos opciones del SDK para reducir el razonamiento y la espera.
SIN_RAZONAMIENTO = [
    types.ThinkingConfig(thinking_budget=0),
    types.ThinkingConfig(thinking_level="MINIMAL"),
]
_opcion_razonamiento = 0

_cliente = None


def _obtener_cliente():
    """Crea el cliente cuando hace falta; las reservas funcionan sin clave de Gemini."""
    global _cliente
    if _cliente is None:
        # La API exige un plazo de servidor de al menos 10 s; el cliente espera menos.
        _cliente = genai.Client(
            api_key=os.environ["GOOGLE_API_KEY"],
            http_options=types.HttpOptions(
                timeout=TIEMPO_MAXIMO_MS, headers={"X-Server-Timeout": "10"}
            ),
        )
    return _cliente


def _preguntar_al_modelo(prompt: str) -> str:
    global _opcion_razonamiento
    while True:
        try:
            respuesta = _obtener_cliente().models.generate_content(
                model=MODELO,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=INSTRUCCIONES,
                    temperature=0.1,
                    max_output_tokens=150,
                    thinking_config=SIN_RAZONAMIENTO[_opcion_razonamiento],
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True
                    ),
                ),
            )
            return (respuesta.text or "").strip()
        except errors.ClientError as e:
            if e.code == 400 and _opcion_razonamiento + 1 < len(SIN_RAZONAMIENTO):
                _opcion_razonamiento += 1
                continue
            raise


def calentar() -> None:
    """Adelanta la primera llamada para reducir la espera del usuario."""
    if CONTEXTO and os.environ.get("GOOGLE_API_KEY"):
        responder_pregunta("¿Hay que llevar toalla?")


def responder_pregunta(pregunta: str) -> str | None:
    """Devuelve la respuesta, None si no consta en los documentos o MENSAJE_ERROR si falla."""
    if not CONTEXTO:
        return None

    # Si la consulta falla, devuelve un aviso al usuario.
    inicio = time.perf_counter()
    try:
        texto = _preguntar_al_modelo(PLANTILLA.format(contexto=CONTEXTO, pregunta=pregunta))
    except Exception as e:
        print(f"ERROR LLM ({(time.perf_counter() - inicio) * 1000:.0f} ms): {e!r}")
        return MENSAJE_ERROR
    print(f"LLM {MODELO}: {(time.perf_counter() - inicio) * 1000:.0f} ms -> {texto!r}")

    if not texto:  # respuesta vacía (bloqueada o cortada): mejor no inventar
        return MENSAJE_ERROR
    # Acepta NO_ENCONTRADO aunque el modelo añada texto o puntuación.
    if CENTINELA in texto:
        return None
    return texto
