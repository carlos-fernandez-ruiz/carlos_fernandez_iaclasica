"""
Batería de la consulta documental: 5 preguntas con respuesta en los documentos
y 5 sin ella. Llama directamente a rag.py (no hace falta arrancar el webhook).

Uso (desde webhook/, con el .venv activado y GOOGLE_API_KEY en el .env):
    python pruebas/bateria_documental.py

Una pregunta con respuesta pasa si el texto contiene los datos esperados; una
sin respuesta pasa si el modelo devuelve NO_ENCONTRADO. Todas deben tardar
menos de 5 s (el límite de Dialogflow).
"""

import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

WEBHOOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WEBHOOK))
load_dotenv(WEBHOOK.parent / ".env")

import rag  # noqa: E402  (después de load_dotenv)

LIMITE_S = 5

# (pregunta, datos esperados): cada grupo es una lista de alternativas y la
# respuesta debe contener al menos una de cada grupo.
CON_RESPUESTA = [
    ("¿Cuánto cuesta el gimnasio al mes?", [["22,05"]]),
    ("¿Cuánto dura como máximo una sesión de musculación?", [["1 hora", "una hora"]]),
    ("¿Cuántas series y repeticiones de sentadilla trasera tiene la rutina?",
     [["3 series", "tres series"], ["6 repeticiones", "seis repeticiones"]]),
    ("¿Cuánto me cobran si pierdo el carnet?", [["6,00", "6 euros", "seis euros", "6 €"]]),
    ("¿Qué descuento tienen las familias numerosas?", [["25"]]),
]

# Preguntas trampa: temas cercanos a lo que hay en los documentos (precios,
# descuentos, horarios), pero cuya respuesta no aparece.
SIN_RESPUESTA = [
    "¿Hay parking gratuito para los socios?",
    "¿Cuánto cuesta un entrenador personal?",
    "¿El gimnasio tiene wifi?",
    "¿Qué descuento tienen los estudiantes universitarios?",
    "¿Hasta qué hora abre la piscina los sábados?",
]


def frases(texto: str) -> int:
    return len([f for f in re.split(r"(?<=[.!?])\s+", texto) if f.strip()])


def main() -> None:
    print(f"Modelo: {rag.MODELO} | documentos: {len(rag.DOCUMENTOS)} | contexto: {len(rag.CONTEXTO)} caracteres\n")
    casos = [(p, esperado) for p, esperado in CON_RESPUESTA] + [(p, None) for p in SIN_RESPUESTA]
    aciertos, tiempos = 0, []

    for pregunta, esperado in casos:
        inicio = time.perf_counter()
        respuesta = rag.responder_pregunta(pregunta)
        segundos = time.perf_counter() - inicio
        tiempos.append(segundos)

        if respuesta == rag.MENSAJE_ERROR:
            ok, detalle = False, "ERROR del modelo"
        elif esperado is None:
            ok, detalle = respuesta is None, "no encontrado" if respuesta is None else "INVENTA una respuesta"
        elif respuesta is None:
            ok, detalle = False, "NO ENCONTRADO (sí estaba)"
        else:
            texto = respuesta.lower()
            ok = all(any(a.lower() in texto for a in grupo) for grupo in esperado)
            detalle = f"{frases(respuesta)} frase(s)" if ok else "faltan datos esperados"
        ok = ok and segundos < LIMITE_S
        aciertos += ok

        tipo = "SIN" if esperado is None else "CON"
        print(f"[{'OK ' if ok else 'MAL'}] {segundos:4.2f} s  {tipo}  {pregunta}")
        print(f"        {respuesta if respuesta else '(None -> mensaje de no encontrado)'}  [{detalle}]\n")

    print(f"Resultado: {aciertos}/{len(casos)} | tiempo máx. {max(tiempos):.2f} s | "
          f"medio {sum(tiempos) / len(tiempos):.2f} s")


if __name__ == "__main__":
    main()
