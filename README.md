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
   automáticamente: se recuperan desde la Papelera de Windows.)
6. **Guard de seguridad**: ArkivX se niega a operar sobre la raíz de un
   disco o carpetas del sistema (Windows, Program Files, ProgramData,
   System32…). Los archivos en uso o sin permiso se saltan y se reportan,
   nunca se fuerzan.

## Cómo correrlo en Windows

Requisito: Python 3.11 o superior (con Tkinter, que viene incluido en el
instalador oficial de python.org).

### Ventana (GUI)

```bat
cd arkivx
python -m arkivx.app
```

También funciona `python arkivx\app.py`. Flujo: elige la carpeta →
**Escanear** → **Buscar duplicados** / **Generar plan de organización**
(revisas la vista previa) → **Aplicar plan** o **Eliminar duplicados** →
**Deshacer última sesión** si algo no quedó como querías.

### Línea de comandos (CLI)

```bat
cd arkivx
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
con un clic.

## Generar el .exe con PyInstaller

```bat
cd arkivx
pip install pyinstaller
pyinstaller --noconfirm --windowed --name ArkivX arkivx\app.py
```

El ejecutable queda en `dist\ArkivX\ArkivX.exe`. (`--windowed` evita
que se abra una consola detrás de la ventana.)

## Estructura

```
arkivx/
├── arkivx/
│   ├── __init__.py
│   ├── core.py    ← motor: escaneo, hash, duplicados, plan, aplicar,
│   │                papelera/cuarentena, historial y deshacer
│   ├── cli.py     ← línea de comandos (usa core)
│   └── app.py     ← ventana Tkinter (usa core)
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
- Soporte para discos externos y USB, barra de progreso en escaneos
  largos.
