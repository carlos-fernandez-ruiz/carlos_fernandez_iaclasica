"""
Recibe las peticiones de Dialogflow y prepara las respuestas de voz.
Las reglas de reserva están en reservas.py y la consulta documental en rag.py.
Para arrancar y probar el webhook, consulta README.md.
"""

import threading
import time
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import rag  # noqa: E402  (después de load_dotenv)
from datos import DIAS, HORARIOS, MESES, SOCIOS  # noqa: E402
from reservas import (  # noqa: E402
    RESERVAS, Evaluacion, clase_canonica, evaluar_reserva, horas_del_dia,
    leer_fecha, plazas_libres, registrar_reserva,
)


@asynccontextmanager
async def arranque(app: FastAPI):
    # Prepara el modelo sin bloquear las peticiones.
    threading.Thread(target=rag.calentar, daemon=True).start()
    yield


app = FastAPI(lifespan=arranque)

CTX_RESERVA = "ctx_reserva_en_curso"
CTX_FOLLOWUP = "reservar_clase-followup"  # lo exigen los follow-up sí/no


# Utilidades de respuesta

def responder(texto: str, contextos: list | None = None) -> dict:
    """fulfillmentText en SSML; contextos opcionales que sustituyen a los activos."""
    respuesta = {"fulfillmentText": f"<speak>{texto}</speak>"}
    if contextos is not None:
        respuesta["outputContexts"] = contextos
    return respuesta


def pausa(ms: int = 300) -> str:
    return f'<break time="{ms}ms"/>'


def deletrear(texto: str) -> str:
    """El DNI y el código de reserva se leen carácter a carácter y más despacio."""
    return f'<prosody rate="slow"><say-as interpret-as="characters">{texto}</say-as></prosody>'


def fecha_hablada(dia) -> str:
    return f"el {DIAS[dia.weekday()]} {dia.day} de {MESES[dia.month - 1]}"


HORAS_EN_LETRA = ["doce", "una", "dos", "tres", "cuatro", "cinco", "seis",
                  "siete", "ocho", "nueve", "diez", "once"]


def hora_hablada(hora: str) -> str:
    """Convierte '19:30' en 'las siete y media de la tarde' para leerlo en voz alta."""
    h, m = (int(x) for x in hora.split(":"))
    if m == 45:
        h, minutos = h + 1, " menos cuarto"
    else:
        minutos = {0: "", 15: " y cuarto", 30: " y media"}.get(m, f" y {m}")
    if h < 6 or h >= 21:
        franja = "de la noche"
    elif h < 12:
        franja = "de la mañana"
    elif h < 13:
        franja = "del mediodía"
    else:
        franja = "de la tarde"
    numero = HORAS_EN_LETRA[h % 12]
    articulo = "la" if numero == "una" else "las"
    return f"{articulo} {numero}{minutos} {franja}"


def horas_habladas(horas: list[str]) -> str:
    """['09:00', '19:00'] -> 'las nueve de la mañana y las siete de la tarde'."""
    return enumerar([hora_hablada(h) for h in horas])


def enumerar(elementos: list[str]) -> str:
    """['a', 'b', 'c'] -> 'a, b y c'."""
    if len(elementos) <= 1:
        return "".join(elementos)
    return ", ".join(elementos[:-1]) + " y " + elementos[-1]


def plural_dia(numero_dia: int) -> str:
    """Los sábados / los domingos (el resto de días no cambia en plural)."""
    nombre = DIAS[numero_dia]
    return nombre + "s" if nombre.endswith("o") else nombre


# Contextos

def contexto(sesion: str, nombre: str, vida: int, parametros: dict | None = None) -> dict:
    c = {"name": f"{sesion}/contexts/{nombre}", "lifespanCount": vida}
    if parametros is not None:
        c["parameters"] = parametros
    return c


def mantener_reserva(sesion: str, parametros: dict) -> list:
    """Mantiene los datos para confirmar, cancelar o corregir el DNI en el siguiente turno."""
    return [
        contexto(sesion, CTX_RESERVA, 5, parametros),
        contexto(sesion, CTX_FOLLOWUP, 2, parametros),
    ]


def cerrar_reserva(sesion: str) -> list:
    return [contexto(sesion, CTX_RESERVA, 0), contexto(sesion, CTX_FOLLOWUP, 0)]


# Reserva de clases

def explicar_no_disponible(ev: Evaluacion) -> str:
    cuando = fecha_hablada(ev.dia)
    del_dia = "del" + cuando[2:]  # "el lunes 2..." -> "del lunes 2..."
    if ev.estado == "pasada":
        return f"La clase de {ev.clase} {del_dia} a {hora_hablada(ev.hora)} ya ha empezado."
    if ev.estado == "completa":
        return f"La clase de {ev.clase} {del_dia} a {hora_hablada(ev.hora)} está completa."
    if ev.horas_dia:
        return (f"{cuando.capitalize()} hay {ev.clase} a {horas_habladas(ev.horas_dia)}, "
                f"pero no a {hora_hablada(ev.hora)}.")
    return f"{cuando.capitalize()} no hay clase de {ev.clase}."


def gestionar_reserva(sesion: str, clase, fecha, hora, dni) -> dict:
    """Valida la reserva y guarda la sesión propuesta en r_fecha y r_hora del contexto."""
    ev = evaluar_reserva(clase, fecha, hora, dni)
    # Conserva los datos para los siguientes turnos de la reserva.
    parametros = {"clase": clase, "fecha": fecha, "hora": hora, "dni": dni}

    if ev.estado == "dni_no_valido":
        if ev.motivo_dni == "letra":
            texto = (f"La letra no corresponde al DNI {deletrear(ev.dni)}. "
                     f"{pausa(200)}¿Me lo repites?")
        else:
            texto = f"No he entendido bien el DNI. {pausa(200)}Dímelo otra vez: los ocho números y la letra."
        return responder(texto, mantener_reserva(sesion, {**parametros, "estado": "falta_dni"}))

    if ev.estado == "socio_no_encontrado":
        texto = (f"No encuentro ningún socio con el DNI {deletrear(ev.dni)}. {pausa(200)}"
                 "Si lo he entendido mal, repítemelo; si no, pasa por recepción para darte de alta.")
        return responder(texto, mantener_reserva(sesion, {**parametros, "estado": "falta_dni"}))

    if ev.estado == "cuota_impagada":
        texto = (f"{ev.nombre}, tienes una cuota pendiente de pago y no puedo hacer la reserva. "
                 f"{pausa(200)}Pasa por recepción para regularizarla. ¿Te ayudo con otra cosa?")
        return responder(texto, cerrar_reserva(sesion))

    if ev.estado == "datos_incompletos":
        texto = "Me falta algún dato de la reserva. Vuelve a pedírmela con la clase, el día y la hora."
        return responder(texto, cerrar_reserva(sesion))

    if ev.estado == "ya_reservada":
        texto = (f"{ev.nombre}, ya tienes plaza en {ev.clase} {fecha_hablada(ev.dia)} "
                 f"a {hora_hablada(ev.hora)}. {pausa()}¿Te ayudo con otra cosa?")
        return responder(texto, cerrar_reserva(sesion))

    if ev.estado == "disponible":
        texto = (f"{ev.nombre}, te reservo {ev.clase} {fecha_hablada(ev.dia)} a {hora_hablada(ev.hora)}. "
                 f"Quedan {ev.plazas} plazas. {pausa()}¿Confirmo la reserva?")
        pendiente = {**parametros, "estado": "pendiente",
                     "r_fecha": ev.dia.isoformat(), "r_hora": ev.hora}
        return responder(texto, mantener_reserva(sesion, pendiente))

    # sin_sesion, pasada o completa: se propone la sesión con plaza más cercana
    motivo = explicar_no_disponible(ev)
    if ev.alternativa is None:
        texto = (f"{motivo} {pausa(200)}No encuentro otra sesión de {ev.clase} con plaza "
                 "en los próximos días. ¿Te ayudo con otra cosa?")
        return responder(texto, cerrar_reserva(sesion))

    otro_dia, otra_hora = ev.alternativa
    texto = (f"{motivo} {pausa()}La más cercana con plaza es {fecha_hablada(otro_dia)} "
             f"a {hora_hablada(otra_hora)}. ¿Te la reservo?")
    pendiente = {**parametros, "estado": "pendiente",
                 "r_fecha": otro_dia.isoformat(), "r_hora": otra_hora}
    return responder(texto, mantener_reserva(sesion, pendiente))


def gestionar_confirmacion(sesion: str, parametros: dict) -> dict:
    """Recibe la sesión del contexto y vuelve a comprobar las plazas antes de reservar."""
    estado = parametros.get("estado", "")
    clase, dni = parametros.get("clase", ""), parametros.get("dni", "")

    if estado == "falta_dni":
        texto = "Antes de confirmar necesito un DNI válido. Dímelo, por favor."
        originales = {k: parametros.get(k, "") for k in ("clase", "fecha", "hora", "dni")}
        return responder(texto, mantener_reserva(sesion, {**originales, "estado": estado}))

    if estado != "pendiente":
        return responder("No tengo ninguna reserva pendiente de confirmar. ¿Quieres reservar una clase?",
                         cerrar_reserva(sesion))

    ev = evaluar_reserva(clase, parametros.get("r_fecha"), parametros.get("r_hora"), dni)
    if ev.estado != "disponible":
        # Explica qué ha cambiado y, si puede, propone otra sesión
        return gestionar_reserva(sesion, clase, parametros.get("r_fecha"),
                                 parametros.get("r_hora"), dni)

    codigo = registrar_reserva(ev)
    print(f"RESERVA {codigo}: {ev.dni} {ev.clase} {ev.dia} {ev.hora}")
    texto = (f"¡Hecho, {ev.nombre}! Tienes plaza en {ev.clase} {fecha_hablada(ev.dia)} "
             f"a {hora_hablada(ev.hora)}. {pausa()}Tu código de reserva es {deletrear(codigo)}. "
             f"{pausa()}¿Puedo ayudarte en algo más?")
    return responder(texto, cerrar_reserva(sesion))


# Consulta de horarios

def resumen_horario(clase: str) -> str:
    """Redacta el horario semanal de una clase para leerlo en voz alta."""
    partes = [f"los {plural_dia(d)} a {horas_habladas(sorted(horas))}"
              for d, horas in sorted(HORARIOS[clase].items())]
    return enumerar(partes)


def gestionar_horario(parametros: dict) -> dict:
    clase = clase_canonica(parametros.get("clase"))
    dia = leer_fecha(parametros.get("fecha"))

    if clase and dia:
        horas = horas_del_dia(clase, dia)
        if not horas:
            texto = (f"{fecha_hablada(dia).capitalize()} no hay {clase}. "
                     f"{pausa(200)}Hay {clase} {resumen_horario(clase)}.")
        else:
            completas = [h for h in horas if plazas_libres(clase, dia, h) <= 0]
            texto = f"{fecha_hablada(dia).capitalize()} hay {clase} a {horas_habladas(horas)}."
            if completas:
                texto += f" La de {horas_habladas(completas)} está completa."
        return responder(f"{texto} {pausa()}¿Quieres reservar?")

    if clase:
        return responder(f"Hay {clase} {resumen_horario(clase)}. {pausa()}¿Quieres reservar?")

    if dia:
        sesiones = [f"{c} a {horas_habladas(horas_del_dia(c, dia))}"
                    for c in HORARIOS if horas_del_dia(c, dia)]
        if not sesiones:
            return responder(f"{fecha_hablada(dia).capitalize()} no hay clases dirigidas. "
                             "Tenemos clases de lunes a sábado.")
        return responder(f"{fecha_hablada(dia).capitalize()} hay {enumerar(sesiones)}. "
                         f"{pausa()}¿Quieres reservar alguna?")

    return responder(f"Tenemos {enumerar(list(HORARIOS))} de lunes a sábado. "
                     f"{pausa(200)}¿De qué clase quieres el horario?")


# Consulta documental (RAG)

def gestionar_documental(pregunta: str, es_fallback: bool) -> dict:
    respuesta = rag.responder_pregunta(pregunta)
    # Si falla Gemini, Dialogflow usa su respuesta de fallback.
    if es_fallback and respuesta == rag.MENSAJE_ERROR:
        return {}
    if respuesta is None:
        # Si no hay respuesta, ofrece reservas y horarios.
        if es_fallback:
            return responder("No tengo esa información en la normativa del gimnasio. "
                             f"{pausa(200)}Si buscabas otra cosa, puedo reservarte una clase o darte los horarios.")
        return responder("No encuentro esa información en la normativa del gimnasio. "
                         "Puedes preguntarlo en recepción.")
    return responder(escape(respuesta))  # el texto del LLM podría romper el SSML


# Endpoint

def enrutar(body: dict) -> dict:
    sesion = body.get("session", "")
    resultado = body["queryResult"]
    intencion = resultado["intent"]["displayName"]
    parametros = resultado.get("parameters", {})
    pregunta = resultado.get("queryText", "")

    if intencion == "reservar_clase":
        # Si faltan datos, Dialogflow hace la siguiente pregunta.
        if not resultado.get("allRequiredParamsPresent", False):
            return {}
        return gestionar_reserva(sesion, parametros.get("clase"), parametros.get("fecha"),
                                 parametros.get("hora"), parametros.get("dni"))

    if intencion == "reservar_clase - corregir_dni":
        # clase/fecha/hora vienen del contexto (#ctx_reserva_en_curso.x); dni es el nuevo
        return gestionar_reserva(sesion, parametros.get("clase"), parametros.get("fecha"),
                                 parametros.get("hora"), parametros.get("dni"))

    if intencion == "reservar_clase - si":
        return gestionar_confirmacion(sesion, parametros)

    if intencion == "consultar_horario":
        return gestionar_horario(parametros)

    if intencion == "consulta_documental":
        return gestionar_documental(pregunta, es_fallback=False)

    if intencion == "Default Fallback Intent":
        return gestionar_documental(pregunta, es_fallback=True)

    # Respuesta para intenciones sin gestionar.
    return responder("Todavía no sé gestionar esa petición.")


@app.post("/webhook")
async def webhook(request: Request):
    inicio = time.perf_counter()
    body = await request.json()
    resultado = body.get("queryResult", {})

    # Registra la petición para depurar errores.
    print("-" * 50)
    print("INTENCION:", resultado.get("intent", {}).get("displayName"))
    print("PARAMETROS:", resultado.get("parameters", {}))
    print("TEXTO:", resultado.get("queryText", ""))

    try:
        respuesta = enrutar(body)
    except Exception as e:
        print("ERROR WEBHOOK:", repr(e))
        respuesta = responder("Perdona, ha habido un problema. ¿Puedes repetirlo?")

    print("RESPUESTA:", respuesta.get("fulfillmentText", "(vacía: prompt de Dialogflow)"))
    print(f"TIEMPO: {(time.perf_counter() - inicio) * 1000:.0f} ms")
    return respuesta


@app.get("/")
def raiz():
    """Devuelve el estado del webhook para comprobar la conexión."""
    return {
        "estado": "ok",
        "socios": len(SOCIOS),
        "reservas_en_memoria": sum(len(d) for d in RESERVAS.values()),
        "documentos_cargados": len(rag.DOCUMENTOS),
    }
