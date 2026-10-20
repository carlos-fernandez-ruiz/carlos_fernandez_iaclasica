"""Socios y horarios ficticios para probar el asistente."""

# DNI normalizado → socio. Coinciden con los ejemplos del agente.
SOCIOS = {
    "12345678Z": {"nombre": "Ana", "cuota_al_dia": True},
    "11111111H": {"nombre": "Marta", "cuota_al_dia": True},
    "87654321X": {"nombre": "Luis", "cuota_al_dia": False},  # cuota impagada
}

# Clase → día (0 = lunes) → hora → (aforo, ocupadas).
# Las plazas ocupadas se repiten cada semana; las nuevas reservas se suman aparte.
HORARIOS = {
    "yoga": {
        0: {"09:00": (15, 4), "19:00": (15, 12)},
        2: {"09:00": (15, 3), "19:00": (15, 14)},
        5: {"10:00": (15, 6)},
    },
    "pilates": {
        1: {"10:00": (12, 5), "18:00": (12, 11)},
        3: {"10:00": (12, 2), "18:00": (12, 9)},
    },
    "spinning": {
        0: {"08:00": (20, 10), "19:30": (20, 18)},
        1: {"19:00": (20, 20)},  # completa: sirve para probar "sin plazas"
        2: {"08:00": (20, 7), "19:30": (20, 15)},
        4: {"08:00": (20, 9), "19:30": (20, 19)},
    },
    "zumba": {
        1: {"20:00": (25, 12)},
        3: {"20:00": (25, 20)},
        5: {"11:30": (25, 8)},
    },
    "body pump": {
        0: {"18:00": (18, 10)},
        2: {"18:00": (18, 17)},
        4: {"18:00": (18, 6)},
    },
    "HIIT": {
        1: {"07:30": (10, 3), "19:00": (10, 8)},
        3: {"07:30": (10, 4), "19:00": (10, 10)},  # jueves 19:00 completa
    },
}

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
