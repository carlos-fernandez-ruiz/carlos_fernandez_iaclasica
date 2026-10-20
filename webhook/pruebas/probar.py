"""
Envía peticiones de ejemplo al webhook sin pasar por Dialogflow.

Uso desde webhook/, con el servidor arrancado:
    python pruebas/probar.py
    python pruebas/probar.py 03 09
    python pruebas/probar.py --url https://tu-tunel/webhook

Actualiza las fechas de noviembre de 2026 cuando hayan pasado.
El caso 13 guarda una reserva en memoria; al repetirlo, ya estará reservada.
"""

import argparse
import json
import re
import urllib.request
from pathlib import Path

CARPETA = Path(__file__).resolve().parent


def enviar(url: str, cuerpo: dict) -> dict:
    peticion = urllib.request.Request(
        url, data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(peticion, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def sin_ssml(texto: str) -> str:
    return re.sub(r"<[^>]+>", "", texto)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("filtros", nargs="*", help="prefijos de los ficheros a enviar")
    parser.add_argument("--url", default="http://localhost:8000/webhook")
    args = parser.parse_args()

    for ruta in sorted(CARPETA.glob("*.json")):
        if args.filtros and not any(ruta.name.startswith(f) for f in args.filtros):
            continue
        respuesta = enviar(args.url, json.loads(ruta.read_text(encoding="utf-8")))
        texto = respuesta.get("fulfillmentText")
        print(f"[{ruta.stem}]")
        print("  ", sin_ssml(texto) if texto else "(respuesta vacía: Dialogflow usa su prompt o su respuesta estática)")
        for c in respuesta.get("outputContexts", []):
            nombre = c["name"].rsplit("/", 1)[-1]
            p = c.get("parameters", {})
            extra = f" estado={p.get('estado')} r_fecha={p.get('r_fecha', '')} r_hora={p.get('r_hora', '')}" if p else ""
            print(f"   contexto {nombre} vida={c['lifespanCount']}{extra}")
        print()


if __name__ == "__main__":
    main()
