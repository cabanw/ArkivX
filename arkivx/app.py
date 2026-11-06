"""Interfaz gráfica de ArkivX (Tkinter, biblioteca estándar).

En Windows no requiere instalar nada: Tkinter viene con Python.
Este módulo se puede importar sin pantalla y sin Tk disponible;
la ventana solo se crea al ejecutar main() (python -m arkivx.app
o python arkivx/app.py).

Las operaciones largas (escanear, buscar duplicados, mover, eliminar,
deshacer) corren en un hilo aparte para que la ventana no se congele.
Tkinter no es seguro entre hilos: el hilo de trabajo solo llama a
`core` y deja el resultado en una cola; la ventana lo recoge con
`after()` y actualiza los controles desde el hilo principal.
"""
from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path

try:
    from arkivx import core
except ImportError:  # ejecutado como script suelto (python arkivx/app.py)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from arkivx import core

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # entorno sin Tk (p. ej. un servidor): importar no falla
    tk = None


class ArkivXApp:
    """Ventana principal: diagnóstico, duplicados y organización."""

    def __init__(self, raiz):
        self.raiz = raiz
        self.raiz.title("ArkivX — Cada archivo en su lugar")
        self.raiz.geometry("980x640")
        self.raiz.protocol("WM_DELETE_WINDOW", self._cerrar)

        self.carpeta = tk.StringVar()
        self.estado = tk.StringVar(
            value="Elige una carpeta para empezar. "
                  "Nada se mueve ni se borra sin tu confirmación."
        )
        self.resultado_dupes = None
        self.plan = None

        self._cola = queue.Queue()
        self._ocupado = False
        self._botones = []
        self._construir()

    # -- Construcción de la interfaz -------------------------------------
    def _boton(self, padre, texto, comando, **pack):
        boton = ttk.Button(padre, text=texto, command=comando)
        boton.pack(side="left", **pack)
        self._botones.append(boton)
        return boton

    def _construir(self):
        superior = ttk.Frame(self.raiz, padding=10)
        superior.pack(fill="x")
        ttk.Label(superior, text="Carpeta:").pack(side="left")
        ttk.Entry(superior, textvariable=self.carpeta, width=70).pack(
            side="left", fill="x", expand=True, padx=5
        )
        self._boton(superior, "Seleccionar…", self._seleccionar)
        self._boton(superior, "Escanear", self._escanear, padx=(5, 0))

        acciones = ttk.Frame(self.raiz, padding=(10, 0, 10, 5))
        acciones.pack(fill="x")
        self._boton(acciones, "Buscar duplicados", self._buscar_duplicados)
        self._boton(acciones, "Generar plan de organización",
                    self._generar_plan, padx=5)
        self._boton(acciones, "Aplicar plan", self._aplicar_plan)
        self._boton(acciones, "Eliminar duplicados",
                    self._eliminar_duplicados, padx=5)
        self._boton(acciones, "Deshacer última sesión", self._deshacer)

        self.pestanas = ttk.Notebook(self.raiz)
        self.pestanas.pack(fill="both", expand=True, padx=10, pady=5)

        self.txt_diagnostico = self._pestana_texto("Diagnóstico")
        self.tree_dupes = self._pestana_arbol(
            "Duplicados", ("archivo", "tamaño", "acción")
        )
        self.tree_plan = self._pestana_arbol(
            "Plan de organización", ("archivo", "categoría", "destino")
        )

        ttk.Label(self.raiz, textvariable=self.estado, padding=10).pack(
            fill="x", side="bottom"
        )

    def _pestana_texto(self, titulo):
        marco = ttk.Frame(self.pestanas)
        texto = tk.Text(marco, wrap="word")
        texto.pack(fill="both", expand=True)
        self.pestanas.add(marco, text=titulo)
        return texto

    def _pestana_arbol(self, titulo, columnas):
        marco = ttk.Frame(self.pestanas)
        arbol = ttk.Treeview(marco, columns=columnas, show="headings")
        for columna in columnas:
            arbol.heading(columna, text=columna.capitalize())
            arbol.column(columna, width=300 if columna != "tamaño" else 90)
        arbol.pack(fill="both", expand=True)
        self.pestanas.add(marco, text=titulo)
        return arbol

    # -- Trabajo en segundo plano -----------------------------------------
    def _en_segundo_plano(self, mensaje, funcion, al_terminar):
        """Ejecuta funcion() en un hilo; al_terminar(resultado) corre luego
        en el hilo de la ventana. Los botones quedan desactivados mientras
        tanto para que no se lancen dos operaciones a la vez."""
        if self._ocupado:
            return
        self._ocupado = True
        for boton in self._botones:
            boton.state(["disabled"])
        self.estado.set(mensaje)
        self.raiz.config(cursor="watch")

        def trabajo():
            try:
                salida = ("ok", funcion())
            except Exception as exc:  # se muestra en la ventana, no se pierde
                salida = ("error", exc)
            self._cola.put((salida, al_terminar))

        threading.Thread(target=trabajo, daemon=True).start()
        self.raiz.after(100, self._revisar_cola)

    def _revisar_cola(self):
        try:
            (tipo, valor), al_terminar = self._cola.get_nowait()
        except queue.Empty:
            self.raiz.after(100, self._revisar_cola)
            return
        self._ocupado = False
        for boton in self._botones:
            boton.state(["!disabled"])
        self.raiz.config(cursor="")
        if tipo == "error":
            self.estado.set("La operación no se completó.")
            messagebox.showerror("ArkivX", str(valor))
            return
        al_terminar(valor)

    def _cerrar(self):
        if self._ocupado:
            messagebox.showwarning(
                "ArkivX",
                "Hay una operación en curso. Espera a que termine antes de "
                "cerrar para no dejar archivos a medio mover.",
            )
            return
        self.raiz.destroy()

    # -- Acciones ---------------------------------------------------------
    def _seleccionar(self):
        elegida = filedialog.askdirectory(title="Elige la carpeta a organizar")
        if elegida:
            self.carpeta.set(elegida)
            self.resultado_dupes = None
            self.plan = None
            self._limpiar(self.tree_dupes)
            self._limpiar(self.tree_plan)
            self._escanear()

    def _carpeta_valida(self):
        carpeta = self.carpeta.get().strip()
        if not carpeta:
            messagebox.showwarning("ArkivX", "Primero elige una carpeta.")
            return None
        return carpeta

    @staticmethod
    def _limpiar(arbol):
        for fila in arbol.get_children():
            arbol.delete(fila)

    def _escanear(self):
        carpeta = self._carpeta_valida()
        if carpeta:
            self._en_segundo_plano(
                "Escaneando…", lambda: core.escanear(carpeta),
                self._mostrar_diagnostico,
            )

    def _mostrar_diagnostico(self, resultado):
        lineas = [
            f"Carpeta: {resultado['carpeta']}",
            f"Archivos: {resultado['total_archivos']}   "
            f"Tamaño total: {core.formato_tamano(resultado['total_bytes'])}",
            "",
            "Por categoría:",
        ]
        for categoria in core.ORDEN_CATEGORIAS:
            datos = resultado["por_categoria"][categoria]
            if datos["archivos"]:
                lineas.append(
                    f"  {categoria:<14} {datos['archivos']:>5} archivos   "
                    f"{core.formato_tamano(datos['bytes'])}"
                )
        lineas.append("")
        lineas.append("Por extensión:")
        for ext, datos in resultado["por_extension"].items():
            lineas.append(
                f"  {ext:<10} {datos['archivos']:>5} archivos   "
                f"{core.formato_tamano(datos['bytes'])}"
            )
        if resultado["omitidas"]:
            lineas.append("")
            lineas.append(
                f"Carpetas omitidas ({len(resultado['omitidas'])}): ocultas, "
                "de sistema, de aplicaciones o enlaces."
            )
            for omitida in resultado["omitidas"][:50]:
                lineas.append(f"  {omitida['ruta']} — {omitida['motivo']}")
        if resultado["errores"]:
            lineas.append("")
            lineas.append("Omitidos (sin permiso o en uso):")
            for error in resultado["errores"]:
                lineas.append(f"  {error['ruta']} — {error['error']}")
        self.txt_diagnostico.delete("1.0", "end")
        self.txt_diagnostico.insert("1.0", "\n".join(lineas))
        self.pestanas.select(0)
        self.estado.set(
            f"Diagnóstico listo: {resultado['total_archivos']} archivos, "
            f"{core.formato_tamano(resultado['total_bytes'])}."
        )

    def _buscar_duplicados(self):
        carpeta = self._carpeta_valida()
        if carpeta:
            self._en_segundo_plano(
                "Buscando duplicados (puede tardar en carpetas grandes)…",
                lambda: core.encontrar_duplicados(carpeta),
                self._mostrar_duplicados,
            )

    def _mostrar_duplicados(self, resultado):
        self.resultado_dupes = resultado
        self._limpiar(self.tree_dupes)
        for i, grupo in enumerate(resultado["grupos"], 1):
            for archivo in grupo["archivos"]:
                if archivo.get("protegido"):
                    accion = "🔒 protegido (proyecto)"
                elif archivo["ruta"] == grupo["conservar"]:
                    accion = "✓ conservar"
                else:
                    accion = "✗ candidato a eliminar"
                self.tree_dupes.insert(
                    "", "end",
                    values=(archivo["ruta"],
                            core.formato_tamano(grupo["tamano"]),
                            f"Grupo {i} — {accion}"),
                )
        self.pestanas.select(1)
        self.estado.set(
            f"Duplicados: {resultado['total_grupos']} grupos, "
            f"{resultado['total_candidatos']} candidatos, "
            f"espacio recuperable: "
            f"{core.formato_tamano(resultado['espacio_recuperable'])}. "
            "Revisa la lista antes de eliminar."
        )

    def _generar_plan(self):
        carpeta = self._carpeta_valida()
        if carpeta:
            self._en_segundo_plano(
                "Generando plan…", lambda: core.plan_organizar(carpeta),
                self._mostrar_plan,
            )

    def _mostrar_plan(self, plan):
        self.plan = plan
        self._limpiar(self.tree_plan)
        for mov in plan["movimientos"]:
            self.tree_plan.insert(
                "", "end",
                values=(mov["origen"], mov["categoria"], mov["destino"]),
            )
        self.pestanas.select(2)
        mensaje = (f"Plan listo (simulación): {len(plan['movimientos'])} "
                   "movimientos. Nada se ha movido todavía; revisa y pulsa "
                   "«Aplicar plan».")
        if plan["errores"]:
            mensaje += f" {len(plan['errores'])} archivos no entran en el plan."
        self.estado.set(mensaje)

    def _aplicar_plan(self):
        if not self.plan or not self.plan["movimientos"]:
            messagebox.showwarning(
                "ArkivX", "Primero genera el plan de organización.")
            return
        plan = self.plan
        if not messagebox.askyesno(
            "ArkivX",
            f"¿Aplicar el plan en\n{plan['carpeta']}?\n\nSe moverán "
            f"{len(plan['movimientos'])} archivos a sus carpetas "
            "de categoría. Podrás deshacerlo desde el historial.",
        ):
            return
        self.plan = None
        self._limpiar(self.tree_plan)
        self._en_segundo_plano(
            "Moviendo archivos…", lambda: core.aplicar_plan(plan),
            self._plan_aplicado,
        )

    def _plan_aplicado(self, resultado):
        mensaje = (f"Plan aplicado: {len(resultado['movimientos'])} "
                   "archivos movidos.")
        if resultado["errores"]:
            mensaje += f" {len(resultado['errores'])} no se pudieron mover."
            messagebox.showwarning("ArkivX", self._resumen_errores(
                mensaje, resultado["errores"]))
        self._escanear()
        self.estado.set(mensaje)

    def _eliminar_duplicados(self):
        if not self.resultado_dupes or not self.resultado_dupes["grupos"]:
            messagebox.showwarning(
                "ArkivX", "Primero busca duplicados en la carpeta.")
            return
        resultado = self.resultado_dupes
        total = resultado["total_candidatos"]
        if not total:
            messagebox.showinfo(
                "ArkivX", "No hay nada que eliminar: todas las copias están "
                          "dentro de proyectos protegidos.")
            return
        if not messagebox.askyesno(
            "ArkivX",
            f"¿Eliminar {total} duplicados en\n{resultado['carpeta']}?\n\n"
            "Se conserva siempre la copia marcada como «conservar» y cada "
            "archivo se vuelve a verificar antes de eliminarlo. Irán a la "
            "Papelera si send2trash está instalado; si no, a la cuarentena.",
        ):
            return
        self.resultado_dupes = None
        self._limpiar(self.tree_dupes)
        self._en_segundo_plano(
            "Verificando y eliminando duplicados…",
            lambda: core.eliminar_duplicados(resultado),
            self._duplicados_eliminados,
        )

    def _duplicados_eliminados(self, resultado):
        mensaje = (f"Duplicados eliminados: {len(resultado['registros'])}. "
                   f"Omitidos o con error: {len(resultado['errores'])}.")
        if resultado["errores"]:
            messagebox.showwarning("ArkivX", self._resumen_errores(
                mensaje, resultado["errores"]))
        self._escanear()
        self.estado.set(mensaje)

    def _deshacer(self):
        self._en_segundo_plano(
            "Deshaciendo la última sesión…", core.deshacer, self._deshecho)

    def _deshecho(self, resultado):
        if not resultado["ok"]:
            messagebox.showinfo("ArkivX", resultado["mensaje"])
            return
        sesion = resultado["sesion"]
        mensaje = (f"Sesión deshecha ({sesion['tipo']} del {sesion['fecha']}): "
                   f"{len(resultado['revertidos'])} archivos revertidos.")
        if resultado["notas"]:
            mensaje += "\n\n" + "\n".join(resultado["notas"][:20])
        if not resultado["completa"]:
            mensaje = self._resumen_errores(
                mensaje + "\n\nAlgunos archivos no se pudieron revertir (en "
                "uso o sin permiso). Ciérralos y pulsa Deshacer otra vez.",
                resultado["errores"],
            )
        messagebox.showinfo("ArkivX", mensaje)
        primera = mensaje.split("\n")[0]
        if self.carpeta.get().strip():
            self._escanear()
        self.estado.set(primera)

    @staticmethod
    def _resumen_errores(mensaje, errores, maximo=10):
        lineas = [mensaje, ""]
        for error in errores[:maximo]:
            lineas.append(f"• {error.get('ruta', '?')}: {error.get('error', '')}")
        if len(errores) > maximo:
            lineas.append(f"… y {len(errores) - maximo} más.")
        return "\n".join(lineas)


def main() -> int:
    if tk is None:
        print("ArkivX necesita Tkinter para la ventana, y no está "
              "disponible en este Python. Usa el CLI: python -m arkivx.cli",
              file=sys.stderr)
        return 1
    ventana = tk.Tk()
    ArkivXApp(ventana)
    ventana.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
