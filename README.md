# ArkivX — «Cada archivo en su lugar»

App local de escritorio para Windows que **organiza archivos por tipo** y
**limpia duplicados por contenido**, con una regla de oro: **nada se mueve
ni se elimina sin un plan previo que el usuario revisa y aprueba**.

100% local: sin nube, sin cuentas, sin internet. Python 3.11+ y solo la
biblioteca estándar (la Papelera real usa `send2trash`, opcional).

## Qué hace el MVP

1. **Escanear** una carpeta y ver el diagnóstico: total de archivos,
   tamaño, desglose por categoría y por extensión.
2. **Detectar duplicados por contenido** (no por nombre): filtro en tres
   pasos — mismo tamaño → hash parcial (primeros 64 KB) → SHA-256
   completo. En cada grupo sugiere cuál conservar (ruta más corta y, en
   empate, el más antiguo) y calcula el espacio recuperable.
3. **Organizar por tipo** con simulación previa obligatoria: genera el
   plan de movimientos (archivo → carpeta de categoría) y solo lo aplica
   cuando el usuario lo confirma. Categorías: Documentos, Imágenes,
   Videos, Audio, Instaladores, Comprimidos, Código y Otros. Nunca
   sobrescribe: si el destino existe, renombra a `nombre (1).ext`,
   `nombre (2).ext`…
4. **Eliminar duplicados de forma segura**: a la Papelera de Reciclaje
   si `send2trash` está instalado; si no, a una carpeta de cuarentena en
   `~/.arkivx/cuarentena/<fecha-hora>/` preservando la estructura.
5. **Historial con Deshacer**: cada sesión queda registrada en
   `~/.arkivx/historial.json`. Deshacer revierte los movimientos de
   organización y restaura los duplicados de la cuarentena. (Los que
   fueron a la Papelera real se anotan como no restaurables
   automáticamente: se recuperan desde la Papelera de Windows.) Si algún
   archivo no se puede revertir (en uso), la sesión queda pendiente y
   volver a pulsar Deshacer reintenta solo los que faltan. El historial
   se guarda de forma atómica; si se daña, se respalda como
   `historial.danado-<fecha>.json` en lugar de perderse.
6. **Guard de seguridad**: ArkivX se niega a operar sobre la raíz de un
   disco, tu carpeta personal (`C:\Users\TuUsuario`) o la que la contiene
   (`C:\Users`), y las carpetas del sistema (Windows, Program Files,
   ProgramData…) o cualquier cosa dentro de ellas. La ruta se resuelve
   antes de comprobarla, así que un acceso directo/unión que apunte a
   `C:\Windows` también se bloquea. Una carpeta tuya que solo se llame
   «Recovery» o «Windows» sí se puede usar. Los archivos en uso o sin
   permiso se saltan y se reportan, nunca se fuerzan.
   **Discos externos**: la raíz de un disco que no es el del sistema
   (`D:\`, un USB) sí se puede **escanear** y **buscar duplicados** (solo
   leen). **Organizar** sigue bloqueado ahí: elige una subcarpeta. La
   raíz de `C:\` sigue bloqueada para todo.
7. **Qué nunca se toca** (ni se cuenta, ni se mueve, ni se elimina):
   - enlaces simbólicos y uniones (junctions);
   - archivos y carpetas ocultos o de sistema (atributo de Windows o
     nombre que empieza por `.`), `desktop.ini`, `Thumbs.db`, archivos
     de bloqueo de Office `~$…`;
   - carpetas de aplicaciones y dependencias: `AppData`, `node_modules`,
     `.git`, `.venv`, `venv`, `__pycache__`, `site-packages`…;
   - en duplicados, además: archivos vacíos (0 bytes, p. ej. los
     `__init__.py`), enlaces duros al mismo archivo y archivos que solo
     están en la nube (OneDrive), para no forzar su descarga.
8. **Proyectos protegidos**: una carpeta con `.git`, `package.json`,
   `requirements.txt`, `pyproject.toml`, `solution.xml`,
   `[Content_Types].xml`, `.sln`, `.csproj`, `.pbip`… (y todo lo que hay
   debajo) se considera un proyecto o paquete. Las copias de proyectos
   (v1/v2, una solución de Power Platform descomprimida dos veces) son
   intencionadas: sus archivos aparecen como 🔒 *protegido* y **nunca**
   se eliminan. Si un archivo tiene copias sueltas fuera de proyectos, se
   conserva una suelta y solo las demás sueltas son candidatas. Organizar
   también se niega si la carpeta elegida es en sí un proyecto.
   Lo mismo aplica a **catálogos de Lightroom** (`.lrcat`,
   `… Previews.lrdata`) y a **copias de seguridad de Windows**
   (`WindowsImageBackup`, `FileHistory`): se escanean y cuentan, pero
   nunca se organizan ni se eliminan duplicados dentro.
9. **Verificación antes de eliminar**: justo antes de enviar cada
   duplicado a la Papelera/cuarentena, ArkivX vuelve a comprobar (SHA-256)
   que la copia que se conserva sigue existiendo e idéntica y que el
   candidato no cambió. Si algo cambió desde el análisis, se omite.

## Cómo correrlo en Windows

Requisito: Python 3.11 o superior (con Tkinter, que viene incluido en el
instalador oficial de python.org).

Todos los comandos se ejecutan desde la **raíz del repositorio** (la
carpeta que contiene `README.md` y la subcarpeta `arkivx\`).

### Ventana (GUI)

```bat
cd ArkivX
python -m arkivx.app
```

También funciona `python arkivx\app.py`. Flujo: elige la carpeta →
**Escanear** → **Buscar duplicados** / **Generar plan de organización**
(revisas la vista previa) → **Aplicar plan** o **Eliminar duplicados** →
**Deshacer última sesión** si algo no quedó como querías.

### Línea de comandos (CLI)

```bat
cd ArkivX
python -m arkivx.cli scan "C:\Users\TuUsuario\Downloads"
python -m arkivx.cli dupes "C:\Users\TuUsuario\Downloads"
python -m arkivx.cli organize "C:\Users\TuUsuario\Downloads" --dry-run
python -m arkivx.cli organize "C:\Users\TuUsuario\Downloads" --apply
python -m arkivx.cli trash-dupes "C:\Users\TuUsuario\Downloads" --apply
python -m arkivx.cli undo
python -m arkivx.cli historial
```

Sin `--apply`, `organize` y `trash-dupes` son **simulaciones**: muestran
exactamente qué pasaría y no tocan nada. `scan` y `dupes` aceptan
`--json` para salida máquina-legible.

### Papelera de Reciclaje real (opcional)

```bat
pip install send2trash
```

Sin `send2trash`, los duplicados van a la cuarentena
(`%USERPROFILE%\.arkivx\cuarentena\`), que además sí se puede deshacer
con un clic. Si la carpeta analizada está en otra unidad (USB, `D:`), la
cuarentena se crea en esa misma unidad (`D:\.arkivx-cuarentena\`) para
no copiar archivos grandes entre discos ni llenar `C:`.

### Pruebas

```bat
cd ArkivX
python -m unittest discover -s tests -v
```

## Generar el .exe con PyInstaller

```bat
cd ArkivX
pip install pyinstaller
pyinstaller --noconfirm --windowed --name ArkivX --paths . arkivx\app.py
```

(`--paths .` asegura que PyInstaller encuentre el paquete `arkivx` al
analizar `from arkivx import core`.)

El ejecutable queda en `dist\ArkivX\ArkivX.exe`. (`--windowed` evita
que se abra una consola detrás de la ventana.)

## Estructura

```
ArkivX/                ← raíz del repositorio (ejecutar comandos aquí)
├── arkivx/
│   ├── __init__.py
│   ├── core.py    ← motor: escaneo, hash, duplicados, plan, aplicar,
│   │                papelera/cuarentena, historial y deshacer
│   ├── cli.py     ← línea de comandos (usa core)
│   └── app.py     ← ventana Tkinter (usa core; tareas largas en un hilo)
├── tests/
│   └── test_core.py   ← pruebas unittest del motor
├── requirements.txt   ← vacío en la práctica: solo send2trash opcional
└── README.md
```

Datos del usuario (fuera del proyecto): `%USERPROFILE%\.arkivx\` con
`historial.json` y `cuarentena\`.

## Decisiones del MVP

- **Organizar no es recursivo**: solo se mueven los archivos sueltos de
  la raíz de la carpeta elegida, para no desarmar estructuras que el
  usuario ya tenga hechas. (El escaneo y la búsqueda de duplicados sí
  son recursivos.)
- **Conservar = ruta más corta, luego el más antiguo**: heurística
  simple y predecible; la copia «principal» suele ser la de la ruta más
  directa.
- **Cuarentena por defecto sin send2trash**: preferimos un mecanismo
  propio y reversible a depender de la Papelera sin poder deshacer.
- **Tkinter en vez de PySide6**: cero instalación en Windows; la GUI y el
  CLI comparten el mismo motor (`core.py`), así que cambiar la interfaz
  en el futuro no toca la lógica.

## Fase 2 (fuera del MVP)

- Organización por fecha (subcarpetas año/mes) y reglas personalizadas
  por palabra clave o proyecto.
- Elegir manualmente qué copia conservar y qué duplicados eliminar
  (casillas por archivo en la GUI).
- Limpieza programada con aviso (p. ej. revisar Descargas cada semana).
- Sugerencias: archivos que no se abren hace un año, archivos gigantes.
- Carpetas protegidas configurables por el usuario.
- Barra de progreso en escaneos largos (la ventana ya no se congela:
  las operaciones corren en segundo plano).
