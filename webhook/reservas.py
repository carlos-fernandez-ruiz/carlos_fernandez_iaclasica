"""
Lógica de negocio de las reservas: validación del DNI, consulta de horarios y
plazas, búsqueda de una sesión alternativa y registro de la reserva.

No sabe nada de Dialogflow: recibe valores y devuelve una Evaluacion. El texto
que se dice al usuario lo construye main.py.
"""

import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from datos import HORARIOS, SOCIOS

LETRAS_DNI = "TRWAGMYFPDXBNJZSQVHLCKE"
PATRON_DNI = re.compile(r"^\d{8}[A-Z]$")

# Reservas hechas con el asistente desde que arrancó el webhook (en memoria).
# (clase, fecha ISO, hora) -> DNI de los socios apuntados
RESERVAS: dict[tuple[str, str, str], set[str]] = {}


# DNI

def normalizar_dni(valor) -> str:
    """'12.345.678 z' / '12345678-Z' -> '12345678Z'."""
    return re.sub(r"[\s.\-]", "", str(valor or "")).upper()


def motivo_dni_no_valido(dni: str) -> str | None:
    """None si el DNI (ya normalizado) es válido; si no, 'formato' o 'letra'."""
    if not PATRON_DNI.match(dni):
        return "formato"
    if LETRAS_DNI[int(dni[:8]) % 23] != dni[8]:
        return "letra"
    return None


# Fechas y horas de Dialogflow

def leer_fecha(valor) -> date | None:
    """@sys.date llega como '2026-11-03T12:00:00+01:00'; solo interesa el día."""
    try:
        return datetime.fromisoformat(str(valor)).date()
    except ValueError:
        return None


def leer_hora(valor) -> str | None:
    """@sys.time llega como '2026-10-18T19:00:00+02:00' (con la fecha de hoy);
    solo interesa la hora. También acepta '19:00' (formato guardado en el contexto)."""
    texto = str(valor or "")
    if re.fullmatch(r"\d{2}:\d{2}", texto):
        return texto
    try:
        return datetime.fromisoformat(texto).strftime("%H:%M")
    except ValueError:
        return None


def clase_canonica(valor) -> str | None:
    """'hiit' -> 'HIIT'. None si la clase no existe en los horarios."""
    texto = str(valor or "").strip().lower()
    return next((c for c in HORARIOS if c.lower() == texto), None)


# Horarios y plazas

def horas_del_dia(clase: str, dia: date) -> list[str]:
    return sorted(HORARIOS[clase].get(dia.weekday(), {}))


def plazas_libres(clase: str, dia: date, hora: str) -> int:
    aforo, ocupadas = HORARIOS[clase][dia.weekday()][hora]
    apuntados = RESERVAS.get((clase, dia.isoformat(), hora), set())
    return aforo - ocupadas - len(apuntados)


def ya_apuntado(clase: str, dia: date, hora: str, dni: str) -> bool:
    return dni in RESERVAS.get((clase, dia.isoformat(), hora), set())


def _minutos(hora: str) -> int:
    h, m = hora.split(":")
    return int(h) * 60 + int(m)


def buscar_alternativa(clase: str, dia: date, hora: str, dni: str,
                       ahora: datetime) -> tuple[date, str] | None:
    """
    Sesión con plaza más cercana a la pedida, sin contar las ya pasadas.
    Orden de preferencia: el mismo día, después el día más próximo (a igual
    distancia, el posterior) y, dentro del día, la hora más parecida.
    """
    base = max(dia, ahora.date())
    candidatas = []
    for desplazamiento in range(-3, 8):
        otro_dia = base + timedelta(days=desplazamiento)
        for otra_hora in horas_del_dia(clase, otro_dia):
            if (otro_dia, otra_hora) == (dia, hora):
                continue
            if datetime.combine(otro_dia, time.fromisoformat(otra_hora)) <= ahora:
                continue
            if plazas_libres(clase, otro_dia, otra_hora) <= 0:
                continue
            if ya_apuntado(clase, otro_dia, otra_hora, dni):
                continue
            distancia_dias = (otro_dia - dia).days
            orden = (abs(distancia_dias), distancia_dias < 0,
                     abs(_minutos(otra_hora) - _minutos(hora)))
            candidatas.append((orden, otro_dia, otra_hora))

    if not candidatas:
        return None
    _, otro_dia, otra_hora = min(candidatas)
    return otro_dia, otra_hora


# Evaluación de una reserva

@dataclass
class Evaluacion:
    """
    estado:
      dni_no_valido        motivo_dni = 'formato' | 'letra'
      socio_no_encontrado
      cuota_impagada
      datos_incompletos    falta la clase, la fecha o la hora (o no se entienden)
      sin_sesion           no hay esa clase ese día o a esa hora
      pasada               la sesión ya ha empezado
      completa             no quedan plazas
      ya_reservada         el socio ya está apuntado a esa sesión
      disponible           se puede reservar
    """
    estado: str
    dni: str = ""
    nombre: str = ""
    clase: str = ""
    dia: date | None = None
    hora: str = ""
    motivo_dni: str = ""
    horas_dia: list[str] = field(default_factory=list)
    plazas: int = 0
    alternativa: tuple[date, str] | None = None


def evaluar_reserva(clase, fecha, hora, dni, ahora: datetime | None = None) -> Evaluacion:
    """Recibe los parámetros tal como llegan de Dialogflow y decide qué pasa."""
    ahora = ahora or datetime.now()

    dni = normalizar_dni(dni)
    motivo = motivo_dni_no_valido(dni)
    if motivo:
        return Evaluacion("dni_no_valido", dni=dni, motivo_dni=motivo)

    socio = SOCIOS.get(dni)
    if socio is None:
        return Evaluacion("socio_no_encontrado", dni=dni)

    ev = Evaluacion("", dni=dni, nombre=socio["nombre"])
    if not socio["cuota_al_dia"]:
        ev.estado = "cuota_impagada"
        return ev

    ev.clase = clase_canonica(clase) or ""
    ev.dia = leer_fecha(fecha)
    ev.hora = leer_hora(hora) or ""
    if not (ev.clase and ev.dia and ev.hora):
        ev.estado = "datos_incompletos"
        return ev

    ev.horas_dia = horas_del_dia(ev.clase, ev.dia)
    if ev.hora not in ev.horas_dia:
        ev.estado = "sin_sesion"
    elif datetime.combine(ev.dia, time.fromisoformat(ev.hora)) <= ahora:
        ev.estado = "pasada"
    elif ya_apuntado(ev.clase, ev.dia, ev.hora, dni):
        ev.estado = "ya_reservada"
        return ev
    elif (plazas := plazas_libres(ev.clase, ev.dia, ev.hora)) <= 0:
        ev.estado = "completa"
    else:
        ev.estado = "disponible"
        ev.plazas = plazas
        return ev

    ev.alternativa = buscar_alternativa(ev.clase, ev.dia, ev.hora, dni, ahora)
    return ev


def registrar_reserva(ev: Evaluacion) -> str:
    """Apunta al socio (solo con una evaluación 'disponible') y devuelve el código."""
    clave = (ev.clase, ev.dia.isoformat(), ev.hora)
    RESERVAS.setdefault(clave, set()).add(ev.dni)
    return f"AT{random.randint(1000, 9999)}"
