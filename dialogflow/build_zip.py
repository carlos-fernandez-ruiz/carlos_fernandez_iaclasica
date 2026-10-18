"""
Empaqueta el agente de Dialogflow ES (dialogflow/agent/) en un ZIP listo para
"Settings -> Export and Import -> Restore from ZIP".

Uso:
    python build_zip.py
    python build_zip.py --webhook-url https://xxxx-8000.devtunnels.ms/webhook

Sin --webhook-url el fulfillment queda desactivado (los intents responden con
sus respuestas estaticas). Con --webhook-url se activa y se rellena la URL,
para que un Restore no borre la configuracion de Fulfillment.

Antes de empaquetar valida que todos los JSON se pueden leer y que los
follow-up apuntan a un intent padre que existe.
"""

import argparse
import json
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
ORIGEN = RAIZ / "agent"
DESTINO = RAIZ / "dist" / "agente_gimnasio.zip"


def validar(origen: Path) -> list[str]:
    errores = []
    datos = {}
    for ruta in sorted(origen.rglob("*.json")):
        try:
            datos[ruta] = json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errores.append(f"{ruta.relative_to(origen)}: JSON no valido ({e})")

    intents = {
        d["id"]: d["name"]
        for r, d in datos.items()
        if r.parent.name == "intents" and not r.stem.endswith("_usersays_es")
    }
    for r, d in datos.items():
        if isinstance(d, dict) and "parentId" in d and d["parentId"] not in intents:
            errores.append(f"{r.name}: parentId {d['parentId']} no existe")

    for nombre in ("agent.json", "package.json"):
        if not (origen / nombre).exists():
            errores.append(f"falta {nombre}")
    return errores


def construir(webhook_url: str | None) -> None:
    errores = validar(ORIGEN)
    if errores:
        print("El agente tiene errores:")
        for e in errores:
            print("  -", e)
        sys.exit(1)

    DESTINO.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(DESTINO, "w", zipfile.ZIP_DEFLATED) as zf:
        for ruta in sorted(ORIGEN.rglob("*.json")):
            nombre = ruta.relative_to(ORIGEN).as_posix()
            contenido = ruta.read_text(encoding="utf-8")
            if nombre == "agent.json" and webhook_url:
                agente = json.loads(contenido)
                agente["webhook"]["url"] = webhook_url
                agente["webhook"]["available"] = True
                contenido = json.dumps(agente, ensure_ascii=False, indent=2)
            zf.writestr(nombre, contenido)

    with zipfile.ZipFile(DESTINO) as zf:
        n = len(zf.namelist())
    print(f"ZIP generado: {DESTINO} ({n} ficheros)")
    print("Webhook:", webhook_url or "desactivado")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--webhook-url", help="URL publica acabada en /webhook")
    construir(parser.parse_args().webhook_url)
