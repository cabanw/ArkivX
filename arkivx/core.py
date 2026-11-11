"""Núcleo de ArkivX: el motor completo, sin interfaz gráfica.

Funciones principales:
- escanear(carpeta): estadísticas de una carpeta (recursivo).
- encontrar_duplicados(carpeta): duplicados por contenido
  (tamaño -> hash parcial de 64 KB -> SHA-256 completo).
- plan_organizar(carpeta): plan de movimientos por tipo de archivo
  (solo archivos sueltos en la raíz; es una SIMULACIÓN, no mueve nada).
- aplicar_plan(plan): ejecuta el plan y lo registra en el historial.
- eliminar_duplicados(resultado): envía los candidatos a la Papelera
  (send2trash, si está instalado) o a la carpeta de cuarentena, tras
  volver a verificar que siguen siendo copias idénticas.
- deshacer(): revierte la última sesión registrada.

Datos del programa en ~/.arkivx/:
- historial.json: registro de sesiones (organizar / duplicados).
- cuarentena/<marca-de-tiempo>/: duplicados apartados cuando no hay
  send2trash, preservando la estructura relativa a la carpeta escaneada.
  Si la carpeta escaneada está en otra unidad (USB, D:), la cuarentena
  se crea en <unidad>\\.arkivx-cuarentena\\ para no copiar entre discos.

Regla de oro: ninguna función mueve ni elimina nada sin que exista un
plan previo (el plan de organización o el resultado de duplicados).

Qué se omite siempre (ni se cuenta, ni se mueve, ni se elimina):
- enlaces simbólicos y uniones (junctions) de Windows;
- carpetas y archivos ocultos o de sistema (atributo de Windows o nombre
  que empieza por «.»), desktop.ini, Thumbs.db, archivos de bloqueo «~$»;
- carpetas de aplicaciones y dependencias: AppData, node_modules,
  .git, .venv, venv, __pycache__, site-packages…
- en duplicados, además: archivos vacíos (0 bytes) y archivos que solo
  están en la nube (OneDrive), para no forzar su descarga.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
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
        # RAW de cámara: Nikon, Canon, Sony, Adobe, Olympus, Panasonic,
        # Fujifilm, Pentax, Samsung
        ".nef", ".nrw", ".cr2", ".cr3", ".arw", ".dng", ".orf", ".rw2",
        ".raf", ".pef", ".srw",
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
    "Discos virtuales": {
        ".iso", ".img", ".vhd", ".vhdx", ".vmdk", ".vdi",
    },
}
ORDEN_CATEGORIAS = list(CATEGORIAS) + ["Otros"]
_EXT_A_CATEGORIA = {
    ext: cat for cat, extensiones in CATEGORIAS.items() for ext in extensiones
}

# Carpetas de aplicaciones/dependencias que nunca se recorren: borrar
# "duplicados" ahí dentro rompe programas y proyectos.
CARPETAS_OMITIDAS = {
    "appdata", "node_modules", "__pycache__", "site-packages",
    "venv", ".venv", ".git", ".svn", ".hg", ".idea", ".vscode",
    "system volume information", "$recycle.bin",
}

# Marcadores de proyecto/paquete: una carpeta que contiene alguno de estos
# (y todo lo que hay debajo) es una unidad que funciona completa. Las
# copias de proyectos (v1/v2, una solución descomprimida dos veces…) son
# intencionadas: ArkivX nunca elimina duplicados dentro de ellas.
MARCADORES_PROYECTO = {
    # control de versiones
    ".git", ".hg", ".svn",
    # Python, Node, .NET, Java, Go, Rust, PHP, Ruby
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
    "pipfile", "package.json", "go.mod", "cargo.toml", "pom.xml",
    "build.gradle", "build.gradle.kts", "composer.json", "gemfile",
    "makefile", "cmakelists.txt", "dockerfile",
    # Power Platform (solución descomprimida) y paquetes Office/OPC
    "solution.xml", "customizations.xml", "[content_types].xml",
}
# Por extensión: Visual Studio, Xcode, proyectos de Power BI (.pbip) y
# catálogos de Lightroom (.lrcat + carpeta «… Previews.lrdata»).
_SUFIJOS_PROYECTO = (".sln", ".csproj", ".vbproj", ".fsproj", ".vcxproj",
                     ".xcodeproj", ".pbip", ".pbir", ".pbism",
                     ".lrcat", ".lrdata")

# Carpetas de copias de seguridad: todo lo que hay dentro funciona como un
# conjunto (WindowsImageBackup guarda .vhdx que Windows necesita para
# restaurar). Se escanean, pero nunca se organizan ni se eliminan
# duplicados dentro de ellas.
CARPETAS_RESPALDO = {"windowsimagebackup", "filehistory"}


def _dentro_de_respaldo(ruta: Path) -> bool:
    """True si la ruta es (o está dentro de) una copia de seguridad o un
    catálogo de Lightroom."""
    return any(parte.lower() in CARPETAS_RESPALDO
               or parte.lower().endswith(".lrdata")
               for parte in Path(ruta).parts)


def _es_carpeta_proyecto(nombres) -> bool:
    """True si entre los nombres (archivos y carpetas) hay un marcador."""
    for nombre in nombres:
        n = nombre.lower()
        if n in MARCADORES_PROYECTO or n.endswith(_SUFIJOS_PROYECTO):
            return True
    return False


# Archivos de sistema que viven junto a los del usuario y no se tocan.
ARCHIVOS_SISTEMA = {
    "desktop.ini", "thumbs.db", "ehthumbs.db", ".ds_store",
    "ntuser.dat", "ntuser.ini", "ntuser.pol", "iconcache.db",
}

# Atributos de archivo de Windows (stat_result.st_file_attributes).
_ATRIB_OCULTO = 0x2
_ATRIB_SISTEMA = 0x4
_ATRIB_OFFLINE = 0x1000
_ATRIB_SOLO_NUBE = 0x400000          # FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
_REPARSE_UNION = 0xA0000003          # IO_REPARSE_TAG_MOUNT_POINT (junction)


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


def carpeta_cuarentena(base=None) -> Path:
    """Carpeta de cuarentena, en la misma unidad que `base` si es posible.

    Mover dentro de una misma unidad es un simple renombrado; entre
    unidades sería una copia lenta que además llenaría el disco C:.
    """
    if base is not None:
        ancla = Path(base).anchor
        ancla_inicio = Path.home().anchor
        if ancla and os.path.normcase(ancla) != os.path.normcase(ancla_inicio):
            alterna = Path(ancla) / ".arkivx-cuarentena"
            try:
                alterna.mkdir(exist_ok=True)
                return alterna
            except OSError:
                pass  # unidad de solo lectura u otro problema: usar la principal
    ruta = carpeta_datos() / "cuarentena"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


# ---------------------------------------------------------------------------
# Seguridad: enlaces, archivos de sistema y carpetas protegidas
# ---------------------------------------------------------------------------
def _atributos(st) -> int:
    return getattr(st, "st_file_attributes", 0) or 0


def _es_enlace_st(st) -> bool:
    """True si el lstat corresponde a un enlace simbólico o a una unión."""
    if stat.S_ISLNK(st.st_mode):
        return True
    return getattr(st, "st_reparse_tag", 0) == _REPARSE_UNION


def _es_enlace(ruta) -> bool:
    try:
        return _es_enlace_st(os.lstat(ruta))
    except OSError:
        return False


def _oculto_o_sistema(nombre: str, st) -> bool:
    return (nombre.startswith(".")
            or bool(_atributos(st) & (_ATRIB_OCULTO | _ATRIB_SISTEMA)))


def _es_archivo_sistema(nombre: str, st) -> bool:
    n = nombre.lower()
    return (n in ARCHIVOS_SISTEMA or n.startswith("~$")
            or _oculto_o_sistema(nombre, st))


def _solo_en_nube(st) -> bool:
    return bool(_atributos(st) & (_ATRIB_SOLO_NUBE | _ATRIB_OFFLINE))


def _normalizar(ruta) -> str:
    return os.path.normcase(os.path.abspath(str(ruta)))


def _dentro_de(ruta_norm: str, base_norm: str) -> bool:
    """True si ruta_norm es base_norm o está dentro (ambas normalizadas)."""
    if ruta_norm == base_norm:
        return True
    return ruta_norm.startswith(base_norm.rstrip("\\/") + os.sep)


def _rutas_sistema(ancla: str = "") -> list:
    """Rutas absolutas del sistema operativo que ArkivX nunca toca."""
    if os.name == "nt":
        entorno = os.environ
        rutas = [
            entorno.get("SystemRoot", r"C:\Windows"),
            entorno.get("ProgramFiles", r"C:\Program Files"),
            entorno.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            entorno.get("ProgramData", r"C:\ProgramData"),
        ]
        if ancla:
            rutas += [
                os.path.join(ancla, nombre) for nombre in (
                    "Windows", "Program Files", "Program Files (x86)",
                    "ProgramData", "System Volume Information",
                    "$Recycle.Bin", "Recovery",
                )
            ]
    else:
        rutas = ["/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/proc",
                 "/sbin", "/sys", "/usr", "/System", "/Library"]
    return [_normalizar(r) for r in rutas]


def _resolver(ruta) -> Path:
    p = Path(ruta).expanduser()
    try:
        return p.resolve()
    except OSError:
        return p.absolute()


def _unidad_sistema() -> str:
    """Unidad de Windows («c:»), normalizada; vacío fuera de Windows."""
    if os.name != "nt":
        return ""
    return os.path.normcase(os.environ.get("SystemDrive", "C:")).rstrip("\\/")


def es_raiz_unidad_datos(ruta) -> bool:
    """True si la ruta es la raíz de un disco que NO es el del sistema
    (D:\\, un disco USB…). Solo Windows; las raíces de red no cuentan."""
    if os.name != "nt":
        return False
    p = _resolver(ruta)
    if p.parent != p:
        return False
    unidad = os.path.normcase(p.drive)
    return (bool(re.fullmatch(r"[a-z]:", unidad))
            and unidad != _unidad_sistema())


def es_carpeta_protegida(ruta) -> bool:
    """True si la ruta es peligrosa para operar.

    Protegidas: la raíz de un disco, la carpeta personal del usuario y la
    carpeta que la contiene (C:\\Users), y las carpetas del sistema
    (Windows, Program Files, ProgramData…) o cualquier cosa dentro de
    ellas. La ruta se resuelve primero, así un enlace o unión que apunte
    a C:\\Windows también queda bloqueado. Una carpeta del usuario que
    simplemente se llame «Recovery» o «Windows» NO se bloquea.
    """
    if re.fullmatch(r"[A-Za-z]:[\\/]?", str(ruta).strip()):  # C:, C:\
        return True
    p = _resolver(ruta)
    if p.parent == p:  # raíz del disco (/, C:\)
        return True
    texto = _normalizar(p)
    inicio = _resolver(Path.home())
    if texto in (_normalizar(inicio), _normalizar(inicio.parent)):
        return True
    return any(_dentro_de(texto, s) for s in _rutas_sistema(p.anchor))


def _validar_carpeta(carpeta, solo_lectura: bool = False) -> Path:
    """Comprueba que la carpeta existe y que ArkivX puede operar en ella.

    Con `solo_lectura=True` (escanear, buscar duplicados) se permite la
    raíz de un disco de datos (D:\\, un USB). Organizar nunca la acepta.
    """
    if re.fullmatch(r"[A-Za-z]:", str(carpeta).strip()):  # «D:» -> «D:\»
        carpeta = str(carpeta).strip() + os.sep
    original = Path(carpeta).expanduser()
    if not original.exists():
        raise ValueError(f"La carpeta no existe: {original}")
    if not original.is_dir():
        raise ValueError(f"No es una carpeta: {original}")
    p = _resolver(original)
    if es_raiz_unidad_datos(p):
        if solo_lectura:
            return p
        raise ValueError(
            f"Raíz de disco: se puede escanear y buscar duplicados, pero "
            f"no organizar. Elige una subcarpeta: {p}"
        )
    if es_carpeta_protegida(carpeta) or es_carpeta_protegida(p):
        raise ValueError(
            f"Carpeta protegida (sistema, raíz del disco o carpeta personal), "
            f"ArkivX no la toca: {p}"
        )
    return p


def _iter_archivos(raiz: Path, errores: list, omitidas: list,
                   proyectos: dict | None = None):
    """Recorre la carpeta (recursivo) devolviendo (ruta, lstat) de archivos.

    No sigue enlaces ni uniones, salta carpetas de sistema, ocultas y de
    dependencias (anotadas en `omitidas`) y no devuelve archivos de
    sistema u ocultos. Lo que no se pudo leer se anota en `errores`.

    Si se pasa `proyectos` (dict), se rellena con {carpeta: raíz del
    proyecto} para cada carpeta que está dentro de un proyecto/paquete
    (ver MARCADORES_PROYECTO). Se evalúa antes de omitir subcarpetas, así
    un .git cuenta como marcador aunque no se recorra.
    """
    sistema = _rutas_sistema(raiz.anchor)
    for dirpath, dirnames, filenames in os.walk(raiz):
        actual = Path(dirpath)
        if proyectos is not None:
            padre = proyectos.get(str(actual.parent)) if actual != raiz else None
            # _dentro_de_respaldo mira toda la ruta: cubre también el caso
            # en que la carpeta elegida ya está dentro de un respaldo o de
            # un «… Previews.lrdata» (la raíz no se ve al recorrer).
            if padre is None and (
                    _dentro_de_respaldo(actual)
                    or _es_carpeta_proyecto(dirnames + filenames)):
                padre = str(actual)
            if padre is not None:
                proyectos[str(actual)] = padre
        for nombre_dir in list(dirnames):
            sub = actual / nombre_dir
            try:
                st = os.lstat(sub)
            except OSError as exc:
                errores.append({"ruta": str(sub), "error": str(exc)})
                dirnames.remove(nombre_dir)
                continue
            if _es_enlace_st(st):
                motivo = "Enlace o unión: no se sigue."
            elif any(_dentro_de(_normalizar(sub), s) for s in sistema):
                motivo = "Carpeta del sistema."
            elif (nombre_dir.lower() in CARPETAS_OMITIDAS
                  or _oculto_o_sistema(nombre_dir, st)):
                motivo = "Carpeta oculta, de sistema o de aplicaciones."
            else:
                continue
            dirnames.remove(nombre_dir)
            omitidas.append({"ruta": str(sub), "motivo": motivo})
        for nombre in filenames:
            ruta = actual / nombre
            try:
                st = os.lstat(ruta)
            except OSError as exc:
                errores.append({"ruta": str(ruta), "error": str(exc)})
                continue
            if not stat.S_ISREG(st.st_mode) or _es_enlace_st(st):
                continue
            if _es_archivo_sistema(nombre, st):
                continue
            yield ruta, st


# ---------------------------------------------------------------------------
# 1. Escaneo / diagnóstico
# ---------------------------------------------------------------------------
def escanear(carpeta) -> dict:
    """Estadísticas de la carpeta: totales, por categoría y por extensión."""
    raiz = _validar_carpeta(carpeta, solo_lectura=True)
    por_categoria = {c: {"archivos": 0, "bytes": 0} for c in ORDEN_CATEGORIAS}
    por_extension = {}
    errores = []
    omitidas = []
    total_archivos = 0
    total_bytes = 0
    for ruta, st in _iter_archivos(raiz, errores, omitidas):
        tamano = st.st_size
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
        "omitidas": omitidas,
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

    Se ignoran: archivos vacíos (todos «coinciden» y suelen ser
    necesarios, p. ej. __init__.py), enlaces duros al mismo archivo
    (borrarlos no libera espacio) y archivos que solo están en la nube.

    Archivos dentro de un proyecto/paquete (carpeta con .git,
    package.json, solution.xml…) se marcan «protegido»: se muestran en
    el grupo pero NUNCA son candidatos a eliminar. Si todas las copias
    están protegidas, el grupo no tiene candidatos. Si hay copias sueltas,
    se conserva una suelta y solo las demás sueltas son candidatas.
    """
    raiz = _validar_carpeta(carpeta, solo_lectura=True)
    errores = []
    omitidas = []
    proyectos = {}

    por_tamano = {}
    vistos = set()
    for ruta, st in _iter_archivos(raiz, errores, omitidas, proyectos):
        if st.st_size == 0:
            continue
        if _solo_en_nube(st):
            errores.append({
                "ruta": str(ruta),
                "error": "Solo está en la nube: omitido para no descargarlo.",
            })
            continue
        if st.st_ino:
            clave = (st.st_dev, st.st_ino)
            if clave in vistos:  # enlace duro: es el mismo archivo
                continue
            vistos.add(clave)
        por_tamano.setdefault(st.st_size, []).append((ruta, st.st_mtime))

    grupos = []
    for tamano, entradas in por_tamano.items():
        if len(entradas) < 2:
            continue
        por_parcial = {}
        for ruta, mtime in entradas:
            try:
                por_parcial.setdefault(_hash_parcial(ruta), []).append(
                    (ruta, mtime))
            except OSError as exc:
                errores.append({"ruta": str(ruta), "error": str(exc)})
        for entradas_parcial in por_parcial.values():
            if len(entradas_parcial) < 2:
                continue
            por_hash = {}
            for ruta, mtime in entradas_parcial:
                try:
                    por_hash.setdefault(_hash_completo(ruta), []).append(
                        (ruta, mtime))
                except OSError as exc:
                    errores.append({"ruta": str(ruta), "error": str(exc)})
            for hash_completo, entradas_hash in por_hash.items():
                if len(entradas_hash) < 2:
                    continue
                archivos = []
                for ruta, mtime in entradas_hash:
                    proyecto = proyectos.get(str(ruta.parent))
                    archivos.append({
                        "ruta": str(ruta),
                        "tamano": tamano,
                        "modificado": mtime,
                        "protegido": proyecto is not None,
                        "proyecto": proyecto,
                    })
                sueltos = [a for a in archivos if not a["protegido"]]
                orden = lambda a: (len(a["ruta"]), a["modificado"])  # noqa: E731
                if sueltos:
                    conservar = sorted(sueltos, key=orden)[0]["ruta"]
                    candidatos = [a["ruta"] for a in sueltos
                                  if a["ruta"] != conservar]
                else:
                    conservar = None  # todas protegidas: no se toca ninguna
                    candidatos = []
                grupos.append({
                    "hash": hash_completo,
                    "tamano": tamano,
                    "archivos": archivos,
                    "conservar": conservar,
                    "candidatos": candidatos,
                    "espacio_recuperable": tamano * len(candidatos),
                })

    grupos.sort(key=lambda g: (g["espacio_recuperable"], g["tamano"]),
                reverse=True)
    return {
        "carpeta": str(raiz),
        "grupos": grupos,
        "total_grupos": len(grupos),
        "total_candidatos": sum(len(g["candidatos"]) for g in grupos),
        "espacio_recuperable": sum(g["espacio_recuperable"] for g in grupos),
        "errores": errores,
        "omitidas": omitidas,
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


def _es_archivo_movible(ruta: Path):
    """lstat del archivo si es un archivo normal del usuario; si no, None."""
    st = os.lstat(ruta)
    if not stat.S_ISREG(st.st_mode) or _es_enlace_st(st):
        return None
    if _es_archivo_sistema(ruta.name, st):
        return None
    return st


def plan_organizar(carpeta) -> dict:
    """SIMULACIÓN: plan de movimientos para organizar por tipo.

    Solo archivos sueltos en la raíz de la carpeta (no recursivo). Se
    omiten enlaces, archivos ocultos y de sistema (desktop.ini…).
    No mueve nada; el plan se revisa y luego se pasa a aplicar_plan().
    """
    raiz = _validar_carpeta(carpeta)
    movimientos = []
    errores = []
    reservados = set()
    if _dentro_de_respaldo(raiz):
        raise ValueError(
            f"La carpeta es (o está dentro de) una copia de seguridad o un "
            f"catálogo de Lightroom. Mover sus archivos la dejaría "
            f"inservible; ArkivX no la organiza: {raiz}"
        )
    entradas = sorted(raiz.iterdir(), key=lambda p: p.name.lower())
    if _es_carpeta_proyecto(e.name for e in entradas):
        raise ValueError(
            f"La carpeta parece un proyecto, paquete o catálogo (tiene .git, "
            f"package.json, .lrcat…). Reorganizar sus archivos lo "
            f"rompería; ArkivX no la organiza: {raiz}"
        )
    for entrada in entradas:
        try:
            st = _es_archivo_movible(entrada)
        except OSError as exc:
            errores.append({"ruta": str(entrada), "error": str(exc)})
            continue
        if st is None:
            continue
        categoria = categoria_de(entrada)
        carpeta_cat = raiz / categoria
        if carpeta_cat.exists() and not carpeta_cat.is_dir():
            errores.append({
                "ruta": str(entrada),
                "error": f"Ya existe un archivo llamado «{categoria}» que "
                         "impide crear esa carpeta de categoría.",
            })
            continue
        destino = _destino_unico(carpeta_cat / entrada.name, reservados)
        movimientos.append({
            "origen": str(entrada),
            "destino": str(destino),
            "categoria": categoria,
            "tamano": st.st_size,
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
            if _es_archivo_movible(origen) is None:
                errores.append({
                    "ruta": str(origen),
                    "error": "Ya no es un archivo normal: omitido.",
                })
                continue
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
            errores.append({"ruta": str(origen), "error": str(exc)})
    sesion = _registrar_si_hay("organizar", plan.get("carpeta"), hechos, errores)
    return {"movimientos": hechos, "errores": errores, "sesion": sesion}


# ---------------------------------------------------------------------------
# 4. Eliminar duplicados (Papelera o cuarentena)
# ---------------------------------------------------------------------------
def _enviar_a_cuarentena(ruta: Path, base: Path, sello: str) -> Path:
    """Mueve el archivo a la cuarentena preservando la estructura relativa
    a la carpeta escaneada."""
    try:
        relativo = ruta.relative_to(base)
    except ValueError:
        relativo = Path(ruta.name)
    destino = _destino_unico(carpeta_cuarentena(base) / sello / relativo, set())
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(ruta), str(destino))
    return destino


def _sigue_igual(ruta: Path, grupo: dict) -> bool:
    """True si el archivo sigue existiendo con el mismo tamaño y SHA-256
    que tenía cuando se buscaron los duplicados."""
    st = os.lstat(ruta)
    if not stat.S_ISREG(st.st_mode) or _es_enlace_st(st):
        return False
    if st.st_size != grupo["tamano"]:
        return False
    return _hash_completo(ruta) == grupo["hash"]


def eliminar_duplicados(resultado: dict) -> dict:
    """Elimina los candidatos de un resultado de encontrar_duplicados().

    Antes de tocar nada vuelve a verificar cada grupo: la copia que se
    conserva debe seguir existiendo e idéntica, y cada candidato debe
    seguir siendo idéntico a ella. Si algo cambió desde el análisis, ese
    archivo (o el grupo entero) se omite y se reporta.

    Si send2trash está instalado, van a la Papelera de Reciclaje del
    sistema (quedan registrados como NO restaurables automáticamente).
    Si no, van a la carpeta de cuarentena y SÍ se pueden deshacer.
    El archivo sugerido como «conservar» nunca se toca.

    Si la búsqueda se hizo en la raíz de un disco de datos (D:\\, un USB)
    se niega con ValueError: buscar ahí es solo lectura, eliminar exige
    elegir una subcarpeta (así no se tocan bibliotecas de juegos o apps
    instaladas en ese disco).
    """
    base = Path(resultado.get("carpeta", ""))
    if es_raiz_unidad_datos(base):
        raise ValueError(
            f"Raíz de disco: aquí solo se pueden buscar duplicados, no "
            f"eliminarlos. Elige una subcarpeta y vuelve a buscar: {base}"
        )
    sello = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    try:
        from send2trash import send2trash
    except ImportError:
        send2trash = None

    registros = []
    errores = []
    for grupo in resultado.get("grupos", []):
        if not grupo.get("candidatos") or not grupo.get("conservar"):
            continue  # grupo protegido o sin nada que eliminar
        protegidos = {a["ruta"] for a in grupo.get("archivos", [])
                      if a.get("protegido")}
        conservar = Path(grupo["conservar"])
        try:
            conservar_ok = _sigue_igual(conservar, grupo)
        except OSError:
            conservar_ok = False
        if not conservar_ok:
            for candidato in grupo.get("candidatos", []):
                errores.append({
                    "ruta": candidato,
                    "error": "La copia a conservar ya no existe o cambió "
                             f"({conservar}): grupo omitido por seguridad.",
                })
            continue
        for candidato in grupo.get("candidatos", []):
            ruta = Path(candidato)
            if candidato in protegidos:  # defensa extra: nunca dentro de proyectos
                errores.append({"ruta": candidato,
                                "error": "Dentro de un proyecto: protegido."})
                continue
            try:
                if not _sigue_igual(ruta, grupo):
                    errores.append({
                        "ruta": str(ruta),
                        "error": "Cambió desde el análisis: omitido.",
                    })
                    continue
                if os.path.samefile(ruta, conservar):
                    continue
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
                errores.append({"ruta": str(ruta), "error": str(exc)})

    sesion = _registrar_si_hay(
        "duplicados", resultado.get("carpeta"), registros, errores)
    return {"registros": registros, "errores": errores, "sesion": sesion}


# ---------------------------------------------------------------------------
# 5. Historial y deshacer
# ---------------------------------------------------------------------------
def cargar_historial() -> dict:
    """Lee el historial.

    Si el archivo está dañado no se descarta en silencio: se renombra a
    historial.danado-<fecha>.json (para poder recuperarlo a mano) y se
    empieza uno nuevo. Un error de lectura (archivo bloqueado) se propaga.
    """
    ruta = ruta_historial()
    if not ruta.exists():
        return {"sesiones": []}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        if isinstance(datos, dict) and isinstance(datos.get("sesiones"), list):
            return datos
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    sello = datetime.now().strftime("%Y%m%d-%H%M%S")
    ruta.replace(ruta.with_name(f"historial.danado-{sello}.json"))
    return {"sesiones": []}


def _guardar_historial(historial: dict) -> None:
    """Escritura atómica: archivo temporal + os.replace."""
    ruta = ruta_historial()
    temporal = ruta.with_name(ruta.name + ".tmp")
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporal, ruta)


def registrar_sesion(sesion: dict) -> dict:
    historial = cargar_historial()
    historial["sesiones"].append(sesion)
    _guardar_historial(historial)
    return sesion


def _registrar_si_hay(tipo, carpeta, movimientos, errores):
    """Registra la sesión si hubo movimientos. Si el historial no se puede
    guardar, se reporta como error en lugar de perder el resultado."""
    if not movimientos:
        return None
    sesion = {
        "id": _nuevo_id(),
        "tipo": tipo,
        "fecha": _ahora(),
        "carpeta": carpeta,
        "movimientos": movimientos,
        "deshecha": False,
    }
    try:
        registrar_sesion(sesion)
    except OSError as exc:
        errores.append({
            "ruta": str(ruta_historial()),
            "error": f"No se pudo guardar el historial ({exc}); esta "
                     "sesión no se podrá deshacer automáticamente.",
        })
        return None
    return sesion


def deshacer() -> dict:
    """Revierte la última sesión no deshecha del historial.

    - Sesiones de organización: cada archivo vuelve a su sitio original.
    - Duplicados en cuarentena: se restauran a su ruta original.
    - Duplicados en la Papelera real: se anotan como no restaurables
      automáticamente (se recuperan desde la Papelera del sistema).
    Si el destino original está ocupado, se renombra con ' (1)', ' (2)'…

    Si algún archivo no se puede revertir (en uso, sin permiso), la
    sesión queda pendiente: volver a pulsar Deshacer reintenta solo los
    que faltan. Los archivos que ya no están donde los dejó ArkivX se
    anotan y no bloquean la sesión.
    """
    historial = cargar_historial()
    pendientes = [s for s in historial["sesiones"] if not s.get("deshecha")]
    if not pendientes:
        return {"ok": False, "completa": True,
                "mensaje": "No hay sesiones por deshacer.",
                "revertidos": [], "errores": [], "notas": []}
    sesion = pendientes[-1]

    revertidos = []
    errores = []
    notas = []
    for mov in reversed(sesion.get("movimientos", [])):
        if mov.get("revertido") or mov.get("perdido"):
            continue
        origen = Path(mov["origen"])
        if not mov.get("restaurable", True) or mov.get("destino") is None:
            notas.append(
                f"No restaurable automáticamente (está en la Papelera): {origen}"
            )
            continue
        actual = Path(mov["destino"])
        if not actual.exists():
            mov["perdido"] = True
            notas.append(
                f"Ya no está donde lo dejó ArkivX (¿movido o borrado?): {actual}"
            )
            continue
        try:
            destino_final = origen
            if destino_final.exists():
                destino_final = _destino_unico(destino_final, set())
            destino_final.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(actual), str(destino_final))
            mov["revertido"] = True
            revertidos.append({"de": str(actual), "a": str(destino_final)})
            try:  # limpiar la carpeta de categoría si quedó vacía
                actual.parent.rmdir()
            except OSError:
                pass
        except OSError as exc:
            errores.append({"ruta": str(actual), "error": str(exc)})

    completa = not errores
    if completa:
        sesion["deshecha"] = True
        sesion["fecha_deshacer"] = _ahora()
    else:
        sesion["deshacer_parcial"] = _ahora()
    _guardar_historial(historial)
    return {
        "ok": True,
        "completa": completa,
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
