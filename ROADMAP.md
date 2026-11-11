# ArkivX — Plan de mejora

Estado al 2026-11-10: **v0.1.0 (MVP)**. Escaneo, duplicados por
contenido, organizar por tipo con simulación, cuarentena + Deshacer,
protección de sistema/proyectos/respaldos/discos externos, GUI Tkinter,
CLI, `.exe` de un solo archivo (`packaging\build_exe.ps1`). 35 pruebas
del motor, ninguna de GUI, sin CI.

Principio que no cambia en ninguna fase: **nunca perder un archivo**.
Toda función nueva que mueva o elimine debe tener simulación previa,
Deshacer y una prueba que demuestre que no toca lo protegido.

---

## Corto plazo — v0.2 «Confiable» (2–4 semanas)

Objetivo: que se pueda dar el `.exe` a otra persona sin acompañarla.

### P0 — Validar lo que ya existe
| # | Tarea | Hecho cuando… |
|---|-------|----------------|
| 1 | Pruebas manuales GUI con checklist escrito (`docs/pruebas-manuales.md`): proyecto con `.git`/`package.json`, `node_modules`, Deshacer/Historial, disco externo real (escanear sí; organizar/eliminar bloqueados) | Checklist completo y firmado con fecha en el `.exe` de `main` |
| 2 | Confirmar restauración de los 21 archivos del 6-nov | Los 21 en su ruta original o explicado por qué no |
| 3 | **CI en GitHub Actions** (Windows): `unittest` en cada PR + build del `.exe` como artefacto | PR no se puede mergear con pruebas en rojo |

### P1 — Huecos de seguridad y operación
| # | Tarea | Por qué |
|---|-------|---------|
| 4 | **Limpieza de cuarentena**: mostrar tamaño en la GUI y botón «Vaciar sesiones de más de N días» (con confirmación; marca esas sesiones como no restaurables en el historial) | Hoy `~/.arkivx/cuarentena` crece sin límite |
| 5 | **Cancelar** operaciones largas (escaneo/hash) | En un disco externo grande hoy solo se puede cerrar la ventana |
| 6 | **Barra de progreso** (archivos procesados / total estimado) | Escanear `D:\` puede tardar minutos sin señal de vida |
| 7 | **Log de errores** rotativo en `~/.arkivx/arkivx.log` | Para diagnosticar fallos del `.exe` (no tiene consola) |
| 8 | Versión visible: `__version__` en título de ventana, `--version` en CLI y metadatos del `.exe` | Saber qué build tiene cada quien |

### P2 — Calidad
| # | Tarea |
|---|-------|
| 9 | Pruebas de `cli.py` (códigos de salida, `trash-dupes` en raíz) y pruebas de humo de la GUI (lógica separada de Tkinter) |
| 10 | Prueba de rendimiento con 100 000 archivos sintéticos; fijar tiempo máximo aceptable |
| 11 | Icono propio para el `.exe` y la ventana |

**Entregable v0.2:** release en GitHub con `ArkivX.exe` construido por CI,
notas de versión y checklist manual aprobado.

---

## Largo plazo — v0.3 → v1.0 (1–6 meses)

### v0.3 «Control» — el usuario decide
- **Elegir qué copia conservar** y qué duplicados eliminar (casillas por
  archivo en la GUI). Hoy la heurística decide sola.
- **Carpetas protegidas configurables** (`~/.arkivx/config.json` +
  pantalla de ajustes); incluir bibliotecas de juegos (Steam, Epic,
  Xbox) como sugerencia por defecto.
- Organizar **por fecha** (año/mes) además de por tipo.
- Reglas personalizadas por palabra clave o extensión → carpeta.

### v0.4 «Rápido» — discos grandes
- Caché de hashes (ruta + tamaño + fecha de modificación → SHA-256) en
  SQLite: el segundo escaneo del mismo disco casi instantáneo.
- Hash en paralelo (hilos) con límite para no saturar discos USB.
- Historial en SQLite con límite/rotación (hoy `historial.json` crece sin
  fin).

### v0.5 «Asistente» — sugerencias
- Archivos gigantes, archivos sin abrir hace más de un año, carpetas
  vacías.
- Fotos casi idénticas (hash perceptual) como *sugerencia*, nunca
  eliminación automática.
- Limpieza programada con aviso (p. ej. revisar Descargas cada semana)
  vía Programador de tareas de Windows; nunca elimina sin confirmación.

### v1.0 «Producto»
- `.exe` **firmado** (evita el aviso de SmartScreen) e instalador
  (Inno Setup o MSIX) con acceso directo y desinstalador.
- Actualización: aviso de versión nueva desde GitHub Releases.
- GUI renovada si Tkinter limita (PySide6 / web local); el motor
  `core.py` no cambia gracias a la separación actual.
- Manual de usuario corto con capturas.
- Evaluar soporte macOS/Linux (el motor ya tiene ramas no-Windows).

---

## Riesgos a vigilar
- **Pérdida de datos por una regla nueva**: cada exclusión/protección
  nueva va con prueba de regresión (como `TestDiscoExterno`).
- **OneDrive / archivos solo en la nube**: no forzar descargas en ninguna
  función nueva (caché, sugerencias, fotos similares).
- **Rendimiento en USB lentos**: medir antes de paralelizar.
- **Merge sin revisión**: mantener PR + CI verde como único camino a
  `main`.
