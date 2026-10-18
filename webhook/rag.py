"""
Consulta documental: responde con un modelo de lenguaje usando solo el texto
de los documentos (OCR) como contexto.

Estado: versión del esqueleto de clase adaptada al gimnasio. En la Sesión 3 se
genera data/documentos.json con el OCR offline y en la Sesión 4 se refuerza
contra las alucinaciones (centinela NO_ENCONTRADO, batería de pruebas).

Requiere GOOGLE_API_KEY en el .env. Sin clave o sin documentos, el webhook
sigue funcionando y responde con un mensaje fijo.
"""

import json
import os
import re
from pathlib import Path

from google import genai
from google.genai import types

RUTA_DOCUMENTOS = Path(__file__).resolve().parent.parent / "data" / "documentos.json"

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

INSTRUCCIONES = """Eres el asistente telefónico del Gimnasio Atlas.
Respondes en español, en dos frases como mucho, porque tu respuesta se va a
convertir en voz. No inventes normas, precios ni horarios. Si no sabes algo,
dilo claramente y sugiere preguntar en recepción."""

PLANTILLA = """Responde a la pregunta del usuario usando UNICAMENTE la
informacion del CONTEXTO que viene a continuacion. Si la respuesta no
esta en el contexto, di que no dispones de ese dato y sugiere preguntar
en recepcion. No completes con conocimiento propio.

CONTEXTO:
{contexto}

PREGUNTA: {pregunta}"""

_cliente = None


def _obtener_cliente():
    """El cliente se crea en la primera pregunta: así el webhook arranca aunque
    todavía no haya GOOGLE_API_KEY (la reserva de clases no la necesita)."""
    global _cliente
    if _cliente is None:
        _cliente = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    return _cliente


def seleccionar_documentos(pregunta: str, n: int = 2) -> str:
    """
    Recuperación por palabras clave del esqueleto: cuenta cuántas palabras de la
    pregunta aparecen en cada documento y se queda con los n mejores.
    Con 3-5 documentos cortos se puede pasar todo (context stuffing); se decide
    en la Sesión 4.
    """
    palabras = set(re.findall(r"\w{4,}", pregunta.lower()))

    puntuados = []
    for nombre, texto in DOCUMENTOS.items():
        coincidencias = sum(1 for p in palabras if p in texto.lower())
        puntuados.append((coincidencias, nombre, texto))

    puntuados.sort(key=lambda x: x[0], reverse=True)
    elegidos = [t for c, _, t in puntuados[:n] if c > 0]
    return "\n\n---\n\n".join(elegidos)


def _preguntar_al_modelo(prompt: str) -> str:
    respuesta = _obtener_cliente().models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=INSTRUCCIONES,
            temperature=0.1,
            max_output_tokens=150,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        ),
    )
    return respuesta.text.strip()


def responder_pregunta(pregunta: str) -> str | None:
    """
    Texto de la respuesta, o None si ningún documento tiene relación con la
    pregunta (quien llama decide qué decir en ese caso).
    """
    contexto = seleccionar_documentos(pregunta)
    if not contexto:
        return None

    # Si el modelo falla o tarda hay que devolver algo igualmente: un webhook
    # que lanza una excepción deja al usuario escuchando un silencio.
    try:
        return _preguntar_al_modelo(PLANTILLA.format(contexto=contexto, pregunta=pregunta))
    except Exception as e:
        print("ERROR LLM:", e)
        return MENSAJE_ERROR
