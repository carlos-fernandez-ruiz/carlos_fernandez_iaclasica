# Webhook del Gimnasio Atlas

Recibe peticiones de Dialogflow ES y responde con datos simulados o con información de los documentos.

| Archivo | Función |
|---|---|
| `main.py` | Recibe las peticiones, gestiona contextos y redacta las respuestas de voz |
| `reservas.py` | Valida DNI, cuotas, horarios y plazas |
| `datos.py` | Socios y horarios de prueba |
| `rag.py` | Consulta a Gemini con el texto del OCR |
| `pruebas/` | Peticiones de ejemplo y pruebas de consulta documental |

## Arrancar

Desde `webhook/`, en WSL/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

En PowerShell, usa `python` en lugar de `python3` y activa el entorno con `.venv\Scripts\activate`. Cada sistema necesita su propio entorno virtual.

La consulta documental necesita `GOOGLE_API_KEY` en el `.env` de la raíz. Las reservas y los horarios funcionan sin esa clave. Puedes cambiar el modelo con `GEMINI_MODEL`; por defecto se usa `gemini-3.1-flash-lite`.

La configuración del túnel y del agente está en el [README principal](../README.md).

## Probar sin Dialogflow

Con el webhook arrancado, ejecuta en otra terminal desde `webhook/`:

```bash
python pruebas/probar.py          # Todas las peticiones
python pruebas/probar.py 03 09    # Solo los casos 03 y 09
```

Para enviar una sola petición:

```bash
curl -X POST http://localhost:8000/webhook -H "Content-Type: application/json" -d @pruebas/01_reserva_ok.json
```

En PowerShell, usa `curl.exe`.

| Caso | Resultado esperado |
|---|---|
| 01 / 02 | Pide confirmar la reserva; el 02 acepta un DNI con puntos y espacios |
| 03 / 04 | Pide repetir el DNI por letra incorrecta o formato no válido |
| 05 / 06 | Informa de socio inexistente o cuota pendiente |
| 07–10 | Propone otra sesión si no existe, está completa o ya ha empezado |
| 11 | Deja que Dialogflow pida los datos que faltan |
| 12 | Corrige el DNI sin perder la reserva |
| 13 | Confirma y devuelve un código |
| 14 | Pide un DNI válido antes de confirmar |
| 15–17 | Responde con los horarios disponibles |
| 18 | Responde sobre el uso de chanclas según los documentos |
| 19 / 20 | Indica que la información no está en los documentos |

Las fechas de prueba son de noviembre de 2026. Actualízalas cuando hayan pasado. El caso 13 guarda una reserva en memoria: si lo repites, responderá que el socio ya tiene plaza.

## Consulta documental

`rag.py` envía los cuatro documentos a Gemini en cada pregunta. Pide respuestas de dos frases como máximo y `NO_ENCONTRADO` cuando no haya información suficiente. El webhook convierte ese valor en un aviso al usuario.

El cliente limita la espera de red a 3,5 s por operación, no por consulta completa. Si el modelo falla, devuelve un mensaje fijo. En una pregunta no reconocida por Dialogflow, se conserva la respuesta de fallback del agente si falla Gemini.

Cada llamada muestra el modelo, el tiempo y la respuesta en consola. Para comprobar cinco preguntas con respuesta y cinco sin ella:

```bash
python pruebas/bateria_documental.py
```

Esta prueba necesita la clave de Gemini, pero no el webhook arrancado.

## Reservas entre turnos

El contexto `ctx_reserva_en_curso` guarda `estado`, `r_fecha` y `r_hora`. Si se propone otra sesión, esos campos contienen la alternativa. Al decir «sí», el agente envía esos datos al webhook, que comprueba de nuevo las plazas y registra la reserva.

Las reservas se guardan en memoria y se pierden al reiniciar.
