"""Núcleo de ArkivX: el motor completo, sin interfaz gráfica.

Funciones principales:
- escanear(carpeta): estadísticas de una carpeta (recursivo).
- encontrar_duplicados(carpeta): duplicados por contenido
  (tamaño -> hash parcial de 64 KB -> SHA-256 completo).
- plan_organizar(carpeta): plan de movimientos por tipo de archivo
  (solo archivos sueltos en la raíz; es una SIMULACIÓN, no mueve nada).
- aplicar_plan(plan): ejecuta el plan y lo registra en el historial.
- eliminar_duplicados(resultado): envía los candidatos a la Papelera
  (send2trash, si está instalado) o a la carpeta de cuarentena.
- deshacer(): revierte la última sesión registrada.

Datos del programa en ~/.arkivx/:
- historial.json: registro de sesiones (organizar / duplicados).
- cuarentena/<marca-de-tiempo>/: duplicados apartados cuando no hay
  send2trash, preservando la estructura relativa a la carpeta escaneada.

Regla de oro: ninguna función mueve ni elimina nada sin que exista un
plan previo (el plan de organización o el resultado de duplicados).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

TAMANO_BLOQUE = 1024 * 1024      # lectura por bloques de 1 MB para el hash
TAMANO_PARCIAL = 64 * 1024       # hash parcial: primeros 64 KB

# ---------------------------------------------------------------------------
# Categorías por extensión
# ---------------------------------------------------------------------------
CATEGORIAS = {
    "Documentos": {
        ".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md",
        ".xls", ".xlsx", ".ods", ".csv", ".tsv",
        ".ppt", ".pptx", ".odp",
    },
    "Imágenes": {
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp",
        ".tif", ".tiff", ".ico", ".heic", ".raw",
    },
    "Videos": {
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
        ".m4v", ".mpg", ".mpeg",
    },
    "Audio": {
        ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus",
    },
    "Instaladores": {
        ".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".apk", ".appimage",
    },
    "Comprimidos": {
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz",
    },
    "Código": {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".htm", ".css",
        ".json", ".xml", ".yml", ".yaml", ".java", ".c", ".h", ".cpp",
        ".hpp", ".cs", ".php", ".rb", ".go", ".rs", ".sh", ".bat",
        ".ps1", ".sql", ".ipynb",
    },
}
ORDEN_CATEGORIAS = list(CATEGORIAS) + ["Otros"]
_EXT_A_CATEGORIA = {
    ext: cat for cat, extensiones in CATEGORIAS.items() for ext in extensiones
}

# Guard básico: nombres de carpeta del sistema que ArkivX nunca toca.
CARPETAS_PROTEGIDAS = {
    "windows", "program files", "program files (x86)", "programdata",
    "system volume information", "$recycle.bin", "recovery",
    "system32", "syswow64",
}


def categoria_de(ruta) -> str:
    """Categoría de un archivo según su extensión ('Otros' si no se conoce)."""
    return _EXT_A_CATEGORIA.get(Path(ruta).suffix.lower(), "Otros")


def formato_tamano(num_bytes) -> str:
    """Tamaño legible: 1536 -> '1.5 KB'."""
    valor = float(num_bytes)
    for unidad in ("B", "KB", "MB", "GB", "TB"):
        if valor < 1024 or unidad == "TB":
            if unidad == "B":
                return f"{int(valor)} B"
            return f"{valor:.1f} {unidad}"
        valor /= 1024
    return f"{valor:.1f} TB"


# ---------------------------------------------------------------------------
# Rutas de datos del programa (~/.arkivx)
# ---------------------------------------------------------------------------
def carpeta_datos() -> Path:
    base = Path.home() / ".arkivx"
    base.mkdir(parents=True, exist_ok=True)
    return base


def ruta_historial() -> Path:
    return carpeta_datos() / "historial.json"


def carpeta_cuarentena() -> Path:
    ruta = carpeta_datos() / "cuarentena"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


# ---------------------------------------------------------------------------
# Seguridad: validación de la carpeta de trabajo
# ---------------------------------------------------------------------------
def es_carpeta_protegida(ruta) -> bool:
    """True si la ruta es la raíz de un disco o pasa por una carpeta del sistema.

    Revisa los componentes separando por '/' y por '\\' para que el guard
    funcione igual con rutas Windows y POSIX.
    """
    texto = str(ruta)
    if Path(ruta).parent == Path(ruta):  # raíz del disco (/, C:\ en Windows)
        return True
    if re.fullmatch(r"[A-Za-z]:[\\/]?", texto):  # raíz de unidad: C:, C:\
        return True
    partes = {parte.lower() for parte in Path(ruta).parts}
    partes |= {trozo.lower() for trozo in re.split(r"[\\/]+", texto) if trozo}
    return bool(partes & CARPETAS_PROTEGIDAS)


def _validar_carpeta(carpeta) -> Path:
    p = Path(carpeta).expanduser()
    if not p.exists():
        raise ValueError(f"La carpeta no existe: {p}")
    if not p.is_dir():
        raise ValueError(f"No es una carpeta: {p}")
    if es_carpeta_protegida(p):
        raise ValueError(
            f"Carpeta protegida del sistema, ArkivX no la toca: {p}"
        )
    return p.resolve()


def _iter_archivos(raiz: Path, errores: list):
    """Recorre la carpeta (recursivo) devolviendo rutas de archivos.

    Salta subcarpetas protegidas y reporta lo que no se pudo leer.
    """
    for dirpath, dirnames, filenames in os.walk(raiz):
        for nombre_dir in list(dirnames):
            if nombre_dir.lower() in CARPETAS_PROTEGIDAS:
                errores.append({
                    "ruta": str(Path(dirpath) / nombre_dir),
                    "error": "Carpeta protegida del sistema: omitida.",
                })
                dirnames.remove(nombre_dir)
        for nombre in filenames:
            yield Path(dirpath) / nombre


# ---------------------------------------------------------------------------
# 1. Escaneo / diagnóstico
# ---------------------------------------------------------------------------
def escanear(carpeta) -> dict:
    """Estadísticas de la carpeta: totales, por categoría y por extensión."""
    raiz = _validar_carpeta(carpeta)
    por_categoria = {c: {"archivos": 0, "bytes": 0} for c in ORDEN_CATEGORIAS}
    por_extension = {}
    errores = []
    total_archivos = 0
    total_bytes = 0
    for ruta in _iter_archivos(raiz, errores):
        try:
            tamano = ruta.stat().st_size
        except OSError as exc:
            errores.append({"ruta": str(ruta), "error": str(exc)})
            continue
        cat = categoria_de(ruta)
        por_categoria[cat]["archivos"] += 1
        por_categoria[cat]["bytes"] += tamano
        ext = ruta.suffix.lower() or "(sin extensión)"
        datos = por_extension.setdefault(ext, {"archivos": 0, "bytes": 0})
        datos["archivos"] += 1
        datos["bytes"] += tamano
        total_archivos += 1
        total_bytes += tamano
    return {
        "carpeta": str(raiz),
        "total_archivos": total_archivos,
        "total_bytes": total_bytes,
        "por_categoria": por_categoria,
        "por_extension": dict(
            sorted(por_extension.items(), key=lambda par: -par[1]["bytes"])
        ),
        "errores": errores,
    }


# ---------------------------------------------------------------------------
# 2. Duplicados por contenido
# ---------------------------------------------------------------------------
def _hash_parcial(ruta: Path) -> str:
    """SHA-256 de los primeros 64 KB (filtro rápido)."""
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        h.update(f.read(TAMANO_PARCIAL))
    return h.hexdigest()


def _hash_completo(ruta: Path) -> str:
    """SHA-256 completo, leído por bloques de 1 MB."""
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        while True:
            bloque = f.read(TAMANO_BLOQUE)
            if not bloque:
                break
            h.update(bloque)
    return h.hexdigest()


def encontrar_duplicados(carpeta) -> dict:
    """Agrupa archivos con contenido idéntico.

    Filtro en tres pasos: mismo tamaño -> mismo hash parcial (64 KB) ->
    mismo SHA-256 completo. En cada grupo se sugiere conservar el de la
    ruta más corta (y, en empate, el más antiguo); el resto son candidatos
    a eliminar.
    """
    raiz = _validar_carpeta(carpeta)
    errores = []

    por_tamano = {}
    for ruta in _iter_archivos(raiz, errores):
        try:
            tamano = ruta.stat().st_size
        except OSError as exc:
            errores.append({"ruta": str(ruta), "error": str(exc)})
            continue
        por_tamano.setdefault(tamano, []).append(ruta)

    grupos = []
    for tamano, rutas in por_tamano.items():
        if len(rutas) < 2:
            continue
        por_parcial = {}
        for ruta in rutas:
            try:
                por_parcial.setdefault(_hash_parcial(ruta), []).append(ruta)
            except OSError as exc:
                errores.append({"ruta": str(ruta), "error": str(exc)})
        for rutas_parcial in por_parcial.values():
            if len(rutas_parcial) < 2:
                continue
            por_hash = {}
            for ruta in rutas_parcial:
                try:
                    por_hash.setdefault(_hash_completo(ruta), []).append(ruta)
                except OSError as exc:
                    errores.append({"ruta": str(ruta), "error": str(exc)})
            for hash_completo, rutas_hash in por_hash.items():
                if len(rutas_hash) < 2:
                    continue
                archivos = []
                for ruta in rutas_hash:
                    try:
                        modificado = ruta.stat().st_mtime
                    except OSError:
                        modificado = 0
                    archivos.append({
                        "ruta": str(ruta),
                        "tamano": tamano,
                        "modificado": modificado,
                    })
                conservar = sorted(
                    archivos, key=lambda a: (len(a["ruta"]), a["modificado"])
                )[0]
                grupos.append({
                    "hash": hash_completo,
                    "tamano": tamano,
                    "archivos": archivos,
                    "conservar": conservar["ruta"],
                    "candidatos": [
                        a["ruta"] for a in archivos
                        if a["ruta"] != conservar["ruta"]
                    ],
                    "espacio_recuperable": tamano * (len(archivos) - 1),
                })

    grupos.sort(key=lambda g: g["espacio_recuperable"], reverse=True)
    return {
        "carpeta": str(raiz),
        "grupos": grupos,
        "total_grupos": len(grupos),
        "espacio_recuperable": sum(g["espacio_recuperable"] for g in grupos),
        "errores": errores,
    }


# ---------------------------------------------------------------------------
# 3. Organizar por tipo (plan + aplicar)
# ---------------------------------------------------------------------------
def _destino_unico(destino: Path, reservados: set) -> Path:
    """Nombre libre para el destino: si ya existe, añade ' (1)', ' (2)'…

    Nunca sobrescribe un archivo existente.
    """
    candidato = destino
    numero = 1
    while candidato.exists() or str(candidato) in reservados:
        candidato = destino.with_name(
            f"{destino.stem} ({numero}){destino.suffix}"
        )
        numero += 1
    reservados.add(str(candidato))
    return candidato


def plan_organizar(carpeta) -> dict:
    """SIMULACIÓN: plan de movimientos para organizar por tipo.

    Solo archivos sueltos en la raíz de la carpeta (no recursivo).
    No mueve nada; el plan se revisa y luego se pasa a aplicar_plan().
    """
    raiz = _validar_carpeta(carpeta)
    movimientos = []
    errores = []
    reservados = set()
    entradas = sorted(raiz.iterdir(), key=lambda p: p.name.lower())
    for entrada in entradas:
        if entrada.is_dir() or not entrada.is_file():
            continue
        try:
            tamano = entrada.stat().st_size
        except OSError as exc:
            errores.append({"ruta": str(entrada), "error": str(exc)})
            continue
        categoria = categoria_de(entrada)
        destino = _destino_unico(raiz / categoria / entrada.name, reservados)
        movimientos.append({
            "origen": str(entrada),
            "destino": str(destino),
            "categoria": categoria,
            "tamano": tamano,
        })
    return {"carpeta": str(raiz), "movimientos": movimientos, "errores": errores}


def aplicar_plan(plan: dict) -> dict:
    """Ejecuta un plan de organización y registra la sesión en el historial."""
    hechos = []
    errores = []
    for mov in plan.get("movimientos", []):
        origen = Path(mov["origen"])
        destino = Path(mov["destino"])
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            if destino.exists():  # cambió desde la simulación: no sobrescribir
                destino = _destino_unico(destino, set())
            shutil.move(str(origen), str(destino))
            hechos.append({
                "origen": str(origen),
                "destino": str(destino),
                "categoria": mov.get("categoria"),
            })
        except OSError as exc:
            errores.append({"origen": str(origen), "error": str(exc)})
    sesion = None
    if hechos:
        sesion = {
            "id": _nuevo_id(),
            "tipo": "organizar",
            "fecha": _ahora(),
            "carpeta": plan.get("carpeta"),
            "movimientos": hechos,
            "deshecha": False,
        }
        registrar_sesion(sesion)
    return {"movimientos": hechos, "errores": errores, "sesion": sesion}


# ---------------------------------------------------------------------------
# 4. Eliminar duplicados (Papelera o cuarentena)
# ---------------------------------------------------------------------------
def _enviar_a_cuarentena(ruta: Path, base: Path, sello: str) -> Path:
    """Mueve el archivo a ~/.arkivx/cuarentena/<sello>/ preservando la
    estructura relativa a la carpeta escaneada."""
    try:
        relativo = ruta.relative_to(base)
    except ValueError:
        relativo = Path(ruta.name)
    destino = _destino_unico(carpeta_cuarentena() / sello / relativo, set())
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(ruta), str(destino))
    return destino


def eliminar_duplicados(resultado: dict) -> dict:
    """Elimina los candidatos de un resultado de encontrar_duplicados().

    Si send2trash está instalado, van a la Papelera de Reciclaje del
    sistema (quedan registrados como NO restaurables automáticamente).
    Si no, van a la carpeta de cuarentena y SÍ se pueden deshacer.
    El archivo sugerido como «conservar» nunca se toca.
    """
    base = Path(resultado.get("carpeta", ""))
    sello = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    try:
        from send2trash import send2trash
    except ImportError:
        send2trash = None

    registros = []
    errores = []
    for grupo in resultado.get("grupos", []):
        for candidato in grupo.get("candidatos", []):
            ruta = Path(candidato)
            try:
                if send2trash is not None:
                    send2trash(str(ruta))
                    registros.append({
                        "origen": str(ruta),
                        "destino": None,
                        "metodo": "papelera",
                        "restaurable": False,
                    })
                else:
                    destino = _enviar_a_cuarentena(ruta, base, sello)
                    registros.append({
                        "origen": str(ruta),
                        "destino": str(destino),
                        "metodo": "cuarentena",
                        "restaurable": True,
                    })
            except Exception as exc:  # en uso, sin permiso, papelera falló…
                errores.append({"origen": str(ruta), "error": str(exc)})

    sesion = None
    if registros:
        sesion = {
            "id": _nuevo_id(),
            "tipo": "duplicados",
            "fecha": _ahora(),
            "carpeta": resultado.get("carpeta"),
            "movimientos": registros,
            "deshecha": False,
        }
        registrar_sesion(sesion)
    return {"registros": registros, "errores": errores, "sesion": sesion}


# ---------------------------------------------------------------------------
# 5. Historial y deshacer
# ---------------------------------------------------------------------------
def cargar_historial() -> dict:
    ruta = ruta_historial()
    if ruta.exists():
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            if isinstance(datos, dict) and "sesiones" in datos:
                return datos
        except (OSError, json.JSONDecodeError):
            pass
    return {"sesiones": []}


def _guardar_historial(historial: dict) -> None:
    ruta_historial().write_text(
        json.dumps(historial, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def registrar_sesion(sesion: dict) -> dict:
    historial = cargar_historial()
    historial["sesiones"].append(sesion)
    _guardar_historial(historial)
    return sesion


def deshacer() -> dict:
    """Revierte la última sesión no deshecha del historial.

    - Sesiones de organización: cada archivo vuelve a su sitio original.
    - Duplicados en cuarentena: se restauran a su ruta original.
    - Duplicados en la Papelera real: se anotan como no restaurables
      automáticamente (se recuperan desde la Papelera del sistema).
    Si el destino original está ocupado, se renombra con ' (1)', ' (2)'…
    """
    historial = cargar_historial()
    pendientes = [s for s in historial["sesiones"] if not s.get("deshecha")]
    if not pendientes:
        return {"ok": False, "mensaje": "No hay sesiones por deshacer.",
                "revertidos": [], "errores": [], "notas": []}
    sesion = pendientes[-1]

    revertidos = []
    errores = []
    notas = []
    for mov in reversed(sesion.get("movimientos", [])):
        origen = Path(mov["origen"])
        if not mov.get("restaurable", True) or mov.get("destino") is None:
            notas.append(
                f"No restaurable automáticamente (está en la Papelera): {origen}"
            )
            continue
        actual = Path(mov["destino"])
        try:
            if not actual.exists():
                errores.append({
                    "origen": str(actual),
                    "error": "El archivo ya no está donde lo dejó ArkivX.",
                })
                continue
            destino_final = origen
            if destino_final.exists():
                destino_final = _destino_unico(destino_final, set())
            destino_final.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(actual), str(destino_final))
            revertidos.append({"de": str(actual), "a": str(destino_final)})
            try:  # limpiar la carpeta de categoría si quedó vacía
                actual.parent.rmdir()
            except OSError:
                pass
        except OSError as exc:
            errores.append({"origen": str(actual), "error": str(exc)})

    sesion["deshecha"] = True
    sesion["fecha_deshacer"] = _ahora()
    _guardar_historial(historial)
    return {
        "ok": True,
        "sesion": sesion,
        "revertidos": revertidos,
        "errores": errores,
        "notas": notas,
    }


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------
def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _nuevo_id() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S%f")
