"""
Consulta documental: responde con un modelo de lenguaje usando solo el texto
de los documentos (OCR) como contexto.

- El OCR se hace offline (ocr/ocr.py -> data/documentos.json); aquí solo se lee.
- Context stuffing: los 4 documentos suman ~16.000 caracteres (~4.400 tokens),
  así que van todos en cada pregunta. La selección por palabras clave del
  esqueleto fallaba: para "¿Cuánto cuesta el gimnasio al mes?" no elegía la
  ordenanza de tasas.
- Contra las alucinaciones: si la respuesta no está en los documentos, el modelo
  debe contestar la palabra centinela NO_ENCONTRADO y el webhook la cambia por
  un mensaje fijo.
- Dialogflow corta a los 5 s: la llamada al modelo tiene un tiempo máximo de
  3,5 s y, si se pasa o falla, se responde con un mensaje fijo.

Requiere GOOGLE_API_KEY en el .env. GEMINI_MODEL es opcional.
"""

import json
import os
import time
from pathlib import Path

from google import genai
from google.genai import errors, types

RUTA_DOCUMENTOS = Path(__file__).resolve().parent.parent / "data" / "documentos.json"

# gemini-2.5-flash ya no está disponible para cuentas nuevas. En las pruebas,
# gemini-3.1-flash-lite respondió en ~0,9 s (máx. 1 s) frente a los 2,5 s de
# mediana y picos de 13 s de gemini-3.8-flash, con las mismas respuestas.
MODELO = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
# httpx aplica el límite a cada fase (conectar, leer...), no al total: con la
# conexión y el túnel, 3,5 s deja margen frente a los 5 s de Dialogflow.
TIEMPO_MAXIMO_MS = 3500
CENTINELA = "NO_ENCONTRADO"

MENSAJE_ERROR = "Ahora mismo no puedo consultar la normativa del gimnasio. Pregúntalo en recepción, por favor."


def cargar_documentos() -> dict[str, str]:
    """
    Lee el texto ya extraído por el OCR offline (ocr/ocr.py). Se hace UNA VEZ al
    arrancar: Dialogflow corta a los 5 segundos y el OCR tarda más que eso.
    """
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

# Sin razonamiento la respuesta tarda la mitad. Unos modelos lo desactivan con
# thinking_budget=0 y otros (gemini-3.5-flash-lite, *-latest) lo rechazan con un
# 400 y piden thinking_level; se prueba la primera opción y, si falla, la segunda.
SIN_RAZONAMIENTO = [
    types.ThinkingConfig(thinking_budget=0),
    types.ThinkingConfig(thinking_level="MINIMAL"),
]
_opcion_razonamiento = 0

_cliente = None


def _obtener_cliente():
    """El cliente se crea en la primera pregunta: así el webhook arranca aunque
    todavía no haya GOOGLE_API_KEY (la reserva de clases no la necesita)."""
    global _cliente
    if _cliente is None:
        # timeout corta la espera en el cliente. El SDK también lo enviaría a
        # la API como plazo del servidor (X-Server-Timeout), pero la API exige
        # un mínimo de 10 s y rechaza 4 s con un 400: se fija esa cabecera a 10.
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


def responder_pregunta(pregunta: str) -> str | None:
    """
    Texto de la respuesta, None si la respuesta no está en los documentos, o
    MENSAJE_ERROR si el modelo falla o tarda demasiado.
    """
    if not CONTEXTO:
        return None

    # Si el modelo falla o tarda hay que devolver algo igualmente: un webhook
    # que lanza una excepción deja al usuario escuchando un silencio.
    inicio = time.perf_counter()
    try:
        texto = _preguntar_al_modelo(PLANTILLA.format(contexto=CONTEXTO, pregunta=pregunta))
    except Exception as e:
        print(f"ERROR LLM ({(time.perf_counter() - inicio) * 1000:.0f} ms): {e!r}")
        return MENSAJE_ERROR
    print(f"LLM {MODELO}: {(time.perf_counter() - inicio) * 1000:.0f} ms -> {texto!r}")

    if not texto:  # respuesta vacía (bloqueada o cortada): mejor no inventar
        return MENSAJE_ERROR
    # El modelo a veces añade un punto ("NO_ENCONTRADO.") o una coletilla
    if CENTINELA in texto:
        return None
    return texto
