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

### P1 — Estándares de código (revisión contra estándares generales)

Línea base medida el 2026-11-10: **ruff** 6–8 avisos menores
(`SIM105`, `SIM112`, `SIM117`, `BLE001` except demasiado amplio…),
**4 de 5 archivos** sin formato estándar. Estándar de referencia: PEP 8
(estilo), PEP 257 (docstrings), PEP 484 (tipos).

| # | Tarea | Hecho cuando… |
|---|-------|----------------|
| 12 | `pyproject.toml` con config de **ruff** (reglas `E,F,W,B,UP,SIM,I,N,BLE`) y `ruff format`; aplicar formato en un PR **solo de formato** (sin cambios de lógica, fácil de revisar) | `ruff check` y `ruff format --check` limpios |
| 13 | Corregir los avisos reales (sobre todo `except Exception` demasiado amplios: capturar lo concreto o justificar con comentario) | 0 avisos sin justificar |
| 14 | Tipos en funciones públicas de `core.py` + **mypy** en modo básico | `mypy arkivx` sin errores |
| 15 | **CI bloquea** el PR si falla lint, formato o tipos | Job `lint` obligatorio en `main` |
| 16 | Revisión manual de código por módulo con checklist (`docs/revision-codigo.md`): nombres, funciones largas (>60 líneas) a dividir, duplicación, manejo de errores, mensajes al usuario, docstrings. Empezar por `core.py` (959 líneas) | Checklist aplicado a `core.py`, `cli.py`, `app.py`; hallazgos en issues |
| 17 | Cobertura de pruebas medida (`coverage`) y publicada en CI; meta inicial ≥ 80 % en `core.py` | Reporte en cada PR |

### P1 — Pruebas de seguridad

Línea base medida el 2026-11-10: **bandit** 0 hallazgos en 1 379 líneas;
cero dependencias en tiempo de ejecución (solo stdlib). El riesgo real
de ArkivX no es la red sino **mover/eliminar el archivo equivocado**, así
que las pruebas se centran en eso.

**Análisis automático (en CI):**
| # | Tarea |
|---|-------|
| 18 | **bandit** (SAST para Python) en CI; falla con severidad media o alta |
| 19 | **CodeQL** de GitHub (análisis semántico, gratis en repos públicos) semanal y en cada PR |
| 20 | **pip-audit** de las dependencias del build (PyInstaller) y **Dependabot** para pip y GitHub Actions |
| 21 | Fijar las GitHub Actions por **SHA** en lugar de etiqueta (evita que una etiqueta movida cambie lo que corre) |
| 22 | Escaneo de secretos (**gitleaks** o el de GitHub) en cada push |

**Pruebas de ataque/abuso (tests nuevos en `tests/test_seguridad.py`):**
| # | Caso | Qué debe pasar |
|---|------|----------------|
| 23 | **Carrera (TOCTOU)**: entre analizar y eliminar, el candidato se reemplaza por un enlace/unión a `C:\Windows` o a otro archivo | No se sigue el enlace; el archivo se omite y se reporta |
| 24 | **`historial.json` manipulado**: rutas que apuntan a `C:\Windows`, `..\..\`, otra unidad o la carpeta personal | Deshacer valida cada ruta (dentro de la carpeta original o la cuarentena) y rechaza el resto |
| 25 | Nombres hostiles: rutas > 260 caracteres, Unicode/emoji, nombres reservados (`CON`, `NUL`), espacios/puntos finales | No revienta ni escribe fuera de la carpeta |
| 26 | Uniones y enlaces simbólicos anidados y en bucle | No se recorren; sin bucles infinitos |
| 27 | Archivo en uso o sin permisos durante mover/eliminar | Se salta y se reporta; el historial queda coherente |
| 28 | **Pruebas basadas en propiedades** (`hypothesis`): árboles de carpetas aleatorios → *organizar + deshacer* deja todo idéntico (mismas rutas y SHA-256) | 0 diferencias en miles de casos |

**Revisión manual:**
| # | Tarea |
|---|-------|
| 29 | Modelo de amenazas de una página (`docs/seguridad.md`): qué protege ArkivX, de qué no (malware local con permisos de usuario), supuestos |
| 30 | Revisión de seguridad dirigida de las rutas destructivas: `eliminar_duplicados`, `aplicar_plan`, `deshacer`, `_validar_carpeta` |
| 31 | Permisos de `~/.arkivx` (historial y cuarentena solo para el usuario) |

**Entregable v0.2:** release en GitHub con `ArkivX.exe` construido por CI,
notas de versión, checklist manual aprobado, CI con lint/formato/tipos y
bandit/CodeQL en verde, y los tests de seguridad #23–#28 pasando.

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
- **Seguridad continua**: auditoría completa antes de cada versión mayor
  (revisión manual + `/security-review`), SBOM del `.exe` publicado en
  cada release, checksums SHA-256 de los binarios, `SECURITY.md` con
  cómo reportar vulnerabilidades.
- **Estándares continuos**: revisión de código obligatoria en cada PR
  contra el checklist de `docs/revision-codigo.md`; complejidad
  ciclomática vigilada (ruff `C90`) y cobertura ≥ 90 % en `core.py`.
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
- **Confianza en `historial.json`**: hoy Deshacer usa las rutas que lee
  de ese archivo; cualquier proceso con permisos del usuario puede
  editarlo. Cerrar con #24 antes de distribuir el `.exe` a terceros.
