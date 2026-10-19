# Webhook del Gimnasio Atlas

FastAPI que recibe las llamadas de Dialogflow ES y decide las respuestas a partir de datos simulados.

| Fichero | Para qué |
|-|-|
| `main.py` | Endpoint `/webhook`, enrutado por intent, contextos y redacción de las respuestas (SSML) |
| `reservas.py` | Reglas de negocio: DNI (regex + letra de control), horarios, plazas, alternativa más cercana |
| `datos.py` | Socios y horarios simulados |
| `rag.py` | Consulta documental con Gemini sobre `data/documentos.json` (todo el texto como contexto, centinela `NO_ENCONTRADO`, tiempo máximo) |
| `pruebas/` | Peticiones de ejemplo con el formato de Dialogflow, `probar.py` para lanzarlas y `bateria_documental.py` |

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

`GOOGLE_API_KEY` (en el `.env` de la raíz, ver `.env.example`) solo hace falta para la consulta documental. Sin ella las reservas y los horarios funcionan. `GEMINI_MODEL` es opcional (por defecto `gemini-3.1-flash-lite`).

## Probar sin Dialogflow

Con el webhook arrancado, en otra terminal (desde `webhook/`):

```bash
python pruebas/probar.py            # las 20 peticiones
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
| 18 | Consulta documental con respuesta (chanclas) |
| 19 | Fallback: el modelo responde `NO_ENCONTRADO` → "No tengo esa información en la normativa... puedo reservarte una clase o darte los horarios" |
| 20 | Consulta documental sin respuesta: "No encuentro esa información..." |

## Consulta documental

| Decisión | Por qué |
|-|-|
| Todo el texto del OCR en cada pregunta (context stuffing) | Son ~16.000 caracteres (~4.400 tokens). La selección por palabras clave del esqueleto no elegía la ordenanza de tasas para "¿Cuánto cuesta el gimnasio al mes?" |
| Centinela `NO_ENCONTRADO` | El modelo la devuelve si la respuesta no está en los documentos y el webhook la cambia por un mensaje fijo. Se busca dentro del texto porque a veces añade un punto |
| `gemini-3.1-flash-lite` sin razonamiento | `gemini-2.5-flash` ya no está disponible para cuentas nuevas. En 10 llamadas con todo el contexto: ~0,9 s (máx. 1 s), frente a 2,5 s de mediana y picos de 13 s de `gemini-3.8-flash` |
| Tiempo máximo de 3,5 s | Dialogflow corta a los 5 s. Si el modelo tarda o falla, se responde "Ahora mismo no puedo consultar la normativa...". En el fallback se deja la respuesta estática |
| Fallback también pasa por el modelo | Una pregunta que Dialogflow no reconoce ("¿hay parking?") cae en el fallback. Si el modelo devuelve `NO_ENCONTRADO`, se dice explícitamente que no está en la normativa y se ofrecen reservas y horarios, en vez de un "¿Cómo dices?" |

Cada llamada imprime en la consola del webhook el modelo, los milisegundos y la respuesta (`LLM gemini-3.1-flash-lite: 1158 ms -> ...`).

Batería de 5 preguntas con respuesta en los documentos y 5 sin ella (no necesita el webhook arrancado):

```bash
python pruebas/bateria_documental.py
```

## Cómo se guarda la reserva entre turnos

La sesión que se va a confirmar viaja en el contexto `ctx_reserva_en_curso`. El webhook lo reescribe en cada respuesta con `estado` (`pendiente` o `falta_dni`), `r_fecha` y `r_hora`. Cuando se propone una alternativa, `r_fecha` y `r_hora` son las de la alternativa, así que un "sí" reserva esa sesión. El intent `reservar_clase - si` recibe esos valores como parámetros (`#ctx_reserva_en_curso.*`), comprueba otra vez las plazas y apunta al socio. Las reservas se guardan en memoria y se pierden al reiniciar el webhook.
