"""
Extrae texto y campos de las imágenes con Tesseract y regex.
Cada carpeta de ocr/documentos/ contiene las páginas de un documento.
Guarda el resultado en data/documentos.json para evitar hacer OCR en cada consulta.

Uso desde la raíz: python ocr/ocr.py
"""

import json
import re
import shutil
import time
from datetime import date
from pathlib import Path

import numpy as np
import pytesseract
from PIL import Image

# Configuración

# Si Tesseract no está en el PATH, busca la instalación habitual de Windows.
if shutil.which("tesseract") is None:
    ejecutable_windows = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if ejecutable_windows.is_file():
        pytesseract.pytesseract.tesseract_cmd = str(ejecutable_windows)

RAIZ = Path(__file__).resolve().parent.parent
CARPETA = RAIZ / "ocr" / "documentos"
SALIDA = RAIZ / "data" / "documentos.json"
EXTENSIONES = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp")

# Títulos manuales: el OCR no siempre lee bien los encabezados.
TITULOS = {
    "tasas_instalaciones": "Ordenanza de tasas de instalaciones deportivas y piscinas",
    "normas_gimnasio": "Normas de uso del gimnasio de musculación",
    "vestuarios_taquillas": "Reglamento de instalaciones deportivas: vestuarios, duchas y taquillas",
    "rutina_3_dias": "Rutina de gimnasio de 3 días",
}

# Este modo conserva mejor las filas de las tablas.
CONFIG_TESSERACT = "--psm 4"

# Amplía las capturas para facilitar la lectura de letras pequeñas.
ESCALA = 2  # x3 empeora: en las tablas se pierden filas enteras
LINEA_HORIZONTAL_MIN = 80  # px (ya escalados): más largo que cualquier letra
LINEA_VERTICAL_MIN = 60
GROSOR_LINEA_MAX = 8  # px; evita borrar recuadros rellenos
ALTO_RECUADRO_MIN = 20  # px para detectar un recuadro oscuro


# Preprocesado de imagen

def umbral_otsu(gris: np.ndarray) -> int:
    """Umbral que mejor separa tinta y fondo según el histograma (método de Otsu)."""
    hist = np.bincount(gris.ravel(), minlength=256).astype(float)
    prob = hist / hist.sum()
    peso = np.cumsum(prob)
    media = np.cumsum(prob * np.arange(256))
    with np.errstate(divide="ignore", invalid="ignore"):
        varianza = (media[-1] * peso - media) ** 2 / (peso * (1 - peso))
    return int(np.nanargmax(varianza))


def tramos_largos(tinta: np.ndarray, longitud_min: int) -> np.ndarray:
    """Marca, fila a fila, los tramos continuos de tinta de al menos longitud_min px."""
    mascara = np.zeros_like(tinta)
    for i, fila in enumerate(tinta):
        cambios = np.diff(np.concatenate(([0], fila.astype(np.int8), [0])))
        for inicio, fin in zip(np.where(cambios == 1)[0], np.where(cambios == -1)[0]):
            if fin - inicio >= longitud_min:
                mascara[i, inicio:fin] = True
    return mascara


def rebinarizar_recuadros(gris: np.ndarray, tinta: np.ndarray) -> None:
    """Recupera las letras sobre fondos oscuros con un umbral local. Modifica tinta."""
    filas_oscuras = np.concatenate(([False], tinta.mean(axis=1) > 0.5, [False]))
    cambios = np.diff(filas_oscuras.astype(np.int8))
    for fila_ini, fila_fin in zip(np.where(cambios == 1)[0], np.where(cambios == -1)[0]):
        if fila_fin - fila_ini < ALTO_RECUADRO_MIN:
            continue
        columnas = np.where(tinta[fila_ini:fila_fin].mean(axis=0) > 0.5)[0]
        col_ini, col_fin = columnas[0], columnas[-1] + 1
        bloque = gris[fila_ini:fila_fin, col_ini:col_fin]
        claro = bloque > umbral_otsu(bloque)
        tinta[fila_ini:fila_fin, col_ini:col_fin] = claro if claro.mean() < 0.5 else ~claro


def lineas_de_tabla(tinta: np.ndarray) -> np.ndarray:
    """Líneas finas y largas: horizontales y verticales, sin los recuadros rellenos."""
    horizontales = tramos_largos(tinta, LINEA_HORIZONTAL_MIN)
    horizontales &= ~tramos_largos(horizontales.T, GROSOR_LINEA_MAX + 1).T
    verticales = tramos_largos(tinta.T, LINEA_VERTICAL_MIN).T
    verticales &= ~tramos_largos(verticales, GROSOR_LINEA_MAX + 1)
    return horizontales | verticales


def preprocesar(ruta: Path) -> Image.Image:
    """Amplía la imagen, separa texto y fondo y borra bordes de tabla que confunden al OCR."""
    imagen = Image.open(ruta)
    if imagen.mode in ("RGBA", "LA", "P"):
        imagen = imagen.convert("RGBA")
        fondo = Image.new("RGB", imagen.size, "white")
        fondo.paste(imagen, mask=imagen.split()[-1])
        imagen = fondo
    imagen = imagen.convert("L")
    imagen = imagen.resize((imagen.width * ESCALA, imagen.height * ESCALA), Image.LANCZOS)

    gris = np.array(imagen)
    tinta = gris <= umbral_otsu(gris)
    rebinarizar_recuadros(gris, tinta)
    tinta &= ~lineas_de_tabla(tinta)

    return Image.fromarray(np.where(tinta, 0, 255).astype(np.uint8))


# Extracción de texto

def leer_pagina(ruta: Path) -> str:
    return pytesseract.image_to_string(
        preprocesar(ruta),
        lang="spa",  # español para reconocer tildes y ñ
        config=CONFIG_TESSERACT,
    )


def limpiar_texto(texto: str) -> str:
    """Quita espacios y restos de bordes de tabla del texto reconocido."""
    texto = re.sub(r"[ \t]*[|\[\]][ \t]*", " ", texto)  # restos de bordes de tabla
    texto = re.sub(r"[ \t]{2,}", " ", texto)
    texto = "\n".join(linea.strip() for linea in texto.splitlines())
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


# Extracción y validación con regex

def normalizar_ocr(texto: str) -> str:
    """Corrige O/0 y l/1 en números, solo en la copia usada para extraer campos."""
    texto = re.sub(r"(?<=\d)[Oo]|[Oo](?=\d)", "0", texto)
    texto = re.sub(r"(?<=\d)[lI]|[lI](?=\d)", "1", texto)
    return texto


MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

PATRONES = {
    # 22,05 € / 18,40 €/mes / 6,00 euros / 150 €
    "importe": re.compile(r"(?<![\d,.])(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s?(?:€|euros?\b)", re.I),
    # 01 de enero de 2012 (puede partirse en dos líneas)
    "fecha": re.compile(r"\b(\d{1,2})\s+de\s+(" + "|".join(MESES) + r")\s+de\s+(\d{4})\b", re.I),
    # 7,00 horas / 17:00 h
    "hora": re.compile(r"\b(\d{1,2})[:.,](\d{2})\s?(?:horas?|h)\b", re.I),
    # Artículo 5.2.1 / Art. 20
    "articulo": re.compile(r"\bArt(?:[íi]culo|\.)\s?(\d+(?:\.\d+)*)", re.I),
    # Ley 39/1988
    "ley": re.compile(r"\bLey\s(\d{1,3})/(\d{4})\b"),
    # menores de 12 años / Más de 26 años
    "edad": re.compile(r"\b(\d{1,2})\s?años\b", re.I),
}

# Fila de la rutina: [músculo] ejercicio series repeticiones descanso
MUSCULO = r"Pierna|Pecho|Espalda|B[íi]ceps|Tr[íi]ceps|Abdomin\w*|Trapecio|Hombro"
FILA_RUTINA = re.compile(
    rf"^(?:(?P<musculo>{MUSCULO})\s+)?(?P<ejercicio>[A-ZÁÉÍÓÚ][\wáéíóúñ ]+?)\s+"
    r"(?P<series>\d{1,2})\s+(?P<repeticiones>\d{1,2})\s+(?P<descanso>\d(?:-\d)?)\s?min$",
    re.I,
)
DIA_RUTINA = re.compile(r"^D[íi]a\s?(\d)$", re.I)


def extraer_campos(texto: str) -> tuple[dict, list[str]]:
    """Devuelve campos validados y avisos sobre valores dudosos para revisarlos a mano."""
    texto = normalizar_ocr(texto)
    campos: dict[str, list] = {clave: [] for clave in PATRONES}
    avisos: list[str] = []

    for m in PATRONES["importe"].finditer(texto):
        bruto = m.group(1)
        if "," not in bruto:
            # Un importe sin céntimos puede haber perdido la coma: «4,20 €» → «420€».
            avisos.append(f"importe sin decimales (coma perdida en el OCR): {m.group(0)!r}")
            continue
        campos["importe"].append(float(bruto.replace(".", "").replace(",", ".")))

    for m in PATRONES["fecha"].finditer(texto):
        try:
            campos["fecha"].append(date(int(m.group(3)), MESES[m.group(2).lower()], int(m.group(1))).isoformat())
        except ValueError:
            avisos.append(f"fecha imposible: {m.group(0)!r}")

    for m in PATRONES["hora"].finditer(texto):
        h, mi = int(m.group(1)), int(m.group(2))
        if h <= 23 and mi <= 59:
            campos["hora"].append(f"{h:02d}:{mi:02d}")
        else:
            avisos.append(f"hora imposible: {m.group(0)!r}")

    campos["articulo"] = [m.group(1) for m in PATRONES["articulo"].finditer(texto)]

    for m in PATRONES["ley"].finditer(texto):
        if 1900 <= int(m.group(2)) <= date.today().year:
            campos["ley"].append(f"{m.group(1)}/{m.group(2)}")
        else:
            avisos.append(f"año de ley imposible: {m.group(0)!r}")

    campos["edad"] = [int(m.group(1)) for m in PATRONES["edad"].finditer(texto)]

    ejercicios, dia = [], None
    for linea in texto.splitlines():
        if m := DIA_RUTINA.match(linea):
            dia = int(m.group(1))
        elif m := FILA_RUTINA.match(linea):
            fila = {
                "dia": dia,
                "musculo": m.group("musculo"),
                "ejercicio": m.group("ejercicio").strip(),
                "series": int(m.group("series")),
                "repeticiones": int(m.group("repeticiones")),
                "descanso_min": m.group("descanso"),
            }
            if 1 <= fila["series"] <= 10 and 1 <= fila["repeticiones"] <= 30:
                ejercicios.append(fila)
            else:
                avisos.append(f"fila de rutina fuera de rango: {linea!r}")
    if ejercicios:
        campos["ejercicios"] = ejercicios

    # Conserva el orden y omite duplicados y campos vacíos.
    return {
        clave: (valores if clave == "ejercicios" else list(dict.fromkeys(valores)))
        for clave, valores in campos.items()
        if valores
    }, avisos


# Proceso completo

def procesar_documento(carpeta: Path) -> dict:
    paginas = sorted(
        (r for r in carpeta.iterdir() if r.suffix.lower() in EXTENSIONES),
        key=lambda r: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", r.stem)],
    )
    textos = []
    for ruta in paginas:
        inicio = time.perf_counter()
        textos.append(limpiar_texto(leer_pagina(ruta)))
        print(f"  {carpeta.name}/{ruta.name}: {len(textos[-1])} caracteres en {time.perf_counter() - inicio:.1f} s")

    texto = "\n\n".join(textos)
    campos, avisos = extraer_campos(texto)
    return {
        "documento": carpeta.name,
        "titulo": TITULOS.get(carpeta.name, carpeta.name.replace("_", " ")),
        "paginas": [r.name for r in paginas],
        "texto": texto,
        "campos": campos,
        "avisos": avisos,
    }


def main() -> None:
    print(f"Tesseract {pytesseract.get_tesseract_version()}")
    carpetas = sorted(c for c in CARPETA.iterdir() if c.is_dir())
    if not carpetas:
        print(f"No hay documentos en {CARPETA} (una subcarpeta por documento).")
        return

    documentos = [procesar_documento(c) for c in carpetas]

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(documentos, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{len(documentos)} documentos -> {SALIDA.relative_to(RAIZ)}")
    for d in documentos:
        resumen = ", ".join(f"{k}: {len(v)}" for k, v in d["campos"].items())
        print(f"  {d['documento']}: {len(d['texto'])} caracteres | {resumen}")
        for aviso in d["avisos"]:
            print(f"    AVISO {aviso}")


if __name__ == "__main__":
    main()
