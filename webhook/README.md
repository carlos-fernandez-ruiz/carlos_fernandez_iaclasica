# Webhook del Gimnasio Atlas

FastAPI que recibe las llamadas de Dialogflow ES y decide las respuestas a partir de datos simulados.

| Fichero | Para qué |
|-|-|
| `main.py` | Endpoint `/webhook`, enrutado por intent, contextos y redacción de las respuestas (SSML) |
| `reservas.py` | Reglas de negocio: DNI (regex + letra de control), horarios, plazas, alternativa más cercana |
| `datos.py` | Socios y horarios simulados |
| `rag.py` | Consulta documental con Gemini sobre `data/documentos.json` (se completa en las Sesiones 3 y 4) |
| `pruebas/` | Peticiones de ejemplo con el formato de Dialogflow y `probar.py` para lanzarlas |

## Arrancar

Desde `webhook/`:

WSL / Linux (terminal bash):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Un `.venv` creado en WSL no sirve en Windows ni al revés: si se cambia de entorno, hay que borrarlo y crearlo de nuevo.

`GOOGLE_API_KEY` (en el `.env` de la raíz, ver `.env.example`) solo hace falta para la consulta documental. Sin ella las reservas y los horarios funcionan.

## Probar sin Dialogflow

Con el webhook arrancado, en otra terminal (desde `webhook/`):

```bash
python pruebas/probar.py            # las 19 peticiones
python pruebas/probar.py 03 09      # solo algunas
```

Una sola petición con `curl`:

```bash
curl -X POST http://localhost:8000/webhook -H "Content-Type: application/json" -d @pruebas/01_reserva_ok.json
```

En PowerShell, usar `curl.exe` (no el alias `curl`) con el mismo comando.

| Petición | Resultado esperado |
|-|-|
| 01 / 02 | Resumen y "¿Confirmo la reserva?" (02: DNI con puntos y espacios) |
| 03 | La letra no corresponde al DNI |
| 04 | DNI no entendido |
| 05 | Socio no encontrado |
| 06 | Cuota impagada, se cierra el contexto |
| 07 / 08 | No hay sesión a esa hora / ese día, se propone la más cercana |
| 09 | Clase completa, se propone otra con plaza |
| 10 | Sesión ya pasada, se propone la próxima |
| 11 | Faltan datos: respuesta vacía para que Dialogflow pregunte |
| 12 | Corrección del DNI dentro de la reserva |
| 13 | Confirmación con código de reserva |
| 14 | "Sí" sin DNI válido: lo vuelve a pedir |
| 15-17 | Consulta de horarios (clase y día, solo clase, domingo) |
| 18 / 19 | Consulta documental sin documentos / fallback |

## Cómo se guarda la reserva entre turnos

La sesión que se va a confirmar viaja en el contexto `ctx_reserva_en_curso`. El webhook lo reescribe en cada respuesta con `estado` (`pendiente` o `falta_dni`), `r_fecha` y `r_hora`. Cuando se propone una alternativa, `r_fecha` y `r_hora` son las de la alternativa, así que un "sí" reserva esa sesión. El intent `reservar_clase - si` recibe esos valores como parámetros (`#ctx_reserva_en_curso.*`), comprueba otra vez las plazas y apunta al socio. Las reservas se guardan en memoria y se pierden al reiniciar el webhook.
