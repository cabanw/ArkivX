"""Interfaz gráfica de ArkivX (Tkinter, biblioteca estándar).

En Windows no requiere instalar nada: Tkinter viene con Python.
Este módulo se puede importar sin pantalla y sin Tk disponible;
la ventana solo se crea al ejecutar main() (python -m arkivx.app
o python arkivx/app.py).
"""
from __future__ import annotations

import sys
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

        self.carpeta = tk.StringVar()
        self.estado = tk.StringVar(
            value="Elige una carpeta para empezar. "
                  "Nada se mueve ni se borra sin tu confirmación."
        )
        self.resultado_dupes = None
        self.plan = None

        self._construir()

    # -- Construcción de la interfaz -------------------------------------
    def _construir(self):
        superior = ttk.Frame(self.raiz, padding=10)
        superior.pack(fill="x")
        ttk.Label(superior, text="Carpeta:").pack(side="left")
        ttk.Entry(superior, textvariable=self.carpeta, width=70).pack(
            side="left", fill="x", expand=True, padx=5
        )
        ttk.Button(superior, text="Seleccionar…",
                   command=self._seleccionar).pack(side="left")
        ttk.Button(superior, text="Escanear",
                   command=self._escanear).pack(side="left", padx=(5, 0))

        acciones = ttk.Frame(self.raiz, padding=(10, 0, 10, 5))
        acciones.pack(fill="x")
        ttk.Button(acciones, text="Buscar duplicados",
                   command=self._buscar_duplicados).pack(side="left")
        ttk.Button(acciones, text="Generar plan de organización",
                   command=self._generar_plan).pack(side="left", padx=5)
        ttk.Button(acciones, text="Aplicar plan",
                   command=self._aplicar_plan).pack(side="left")
        ttk.Button(acciones, text="Eliminar duplicados",
                   command=self._eliminar_duplicados).pack(side="left", padx=5)
        ttk.Button(acciones, text="Deshacer última sesión",
                   command=self._deshacer).pack(side="left")

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

    # -- Acciones ---------------------------------------------------------
    def _seleccionar(self):
        elegida = filedialog.askdirectory(title="Elige la carpeta a organizar")
        if elegida:
            self.carpeta.set(elegida)
            self.resultado_dupes = None
            self.plan = None
            self._escanear()

    def _carpeta_valida(self):
        carpeta = self.carpeta.get().strip()
        if not carpeta:
            messagebox.showwarning("ArkivX", "Primero elige una carpeta.")
            return None
        return carpeta

    def _escanear(self):
        carpeta = self._carpeta_valida()
        if not carpeta:
            return
        try:
            resultado = core.escanear(carpeta)
        except ValueError as exc:
            messagebox.showerror("ArkivX", str(exc))
            return
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
        if not carpeta:
            return
        try:
            self.resultado_dupes = core.encontrar_duplicados(carpeta)
        except ValueError as exc:
            messagebox.showerror("ArkivX", str(exc))
            return
        for fila in self.tree_dupes.get_children():
            self.tree_dupes.delete(fila)
        for i, grupo in enumerate(self.resultado_dupes["grupos"], 1):
            for archivo in grupo["archivos"]:
                accion = ("✓ conservar" if archivo["ruta"] == grupo["conservar"]
                          else "✗ candidato a eliminar")
                self.tree_dupes.insert(
                    "", "end",
                    values=(archivo["ruta"],
                            core.formato_tamano(grupo["tamano"]),
                            f"Grupo {i} — {accion}"),
                )
        self.pestanas.select(1)
        self.estado.set(
            f"Duplicados: {self.resultado_dupes['total_grupos']} grupos, "
            f"espacio recuperable: "
            f"{core.formato_tamano(self.resultado_dupes['espacio_recuperable'])}. "
            "Revisa la lista antes de eliminar."
        )

    def _generar_plan(self):
        carpeta = self._carpeta_valida()
        if not carpeta:
            return
        try:
            self.plan = core.plan_organizar(carpeta)
        except ValueError as exc:
            messagebox.showerror("ArkivX", str(exc))
            return
        for fila in self.tree_plan.get_children():
            self.tree_plan.delete(fila)
        for mov in self.plan["movimientos"]:
            self.tree_plan.insert(
                "", "end",
                values=(mov["origen"], mov["categoria"], mov["destino"]),
            )
        self.pestanas.select(2)
        self.estado.set(
            f"Plan listo (simulación): {len(self.plan['movimientos'])} "
            "movimientos. Nada se ha movido todavía; revisa y pulsa "
            "«Aplicar plan»."
        )

    def _aplicar_plan(self):
        if not self.plan or not self.plan["movimientos"]:
            messagebox.showwarning(
                "ArkivX", "Primero genera el plan de organización.")
            return
        if not messagebox.askyesno(
            "ArkivX",
            f"¿Aplicar el plan? Se moverán "
            f"{len(self.plan['movimientos'])} archivos a sus carpetas "
            "de categoría. Podrás deshacerlo desde el historial.",
        ):
            return
        resultado = core.aplicar_plan(self.plan)
        self.plan = None
        for fila in self.tree_plan.get_children():
            self.tree_plan.delete(fila)
        mensaje = (f"Plan aplicado: {len(resultado['movimientos'])} "
                   "archivos movidos.")
        if resultado["errores"]:
            mensaje += f" {len(resultado['errores'])} no se pudieron mover."
        self.estado.set(mensaje)
        self._escanear()

    def _eliminar_duplicados(self):
        if not self.resultado_dupes or not self.resultado_dupes["grupos"]:
            messagebox.showwarning(
                "ArkivX", "Primero busca duplicados en la carpeta.")
            return
        total = sum(len(g["candidatos"])
                    for g in self.resultado_dupes["grupos"])
        if not messagebox.askyesno(
            "ArkivX",
            f"¿Eliminar {total} duplicados? Se conserva siempre la copia "
            "marcada como «conservar». Irán a la Papelera si send2trash "
            "está instalado; si no, a la cuarentena de ~/.arkivx.",
        ):
            return
        resultado = core.eliminar_duplicados(self.resultado_dupes)
        self.resultado_dupes = None
        for fila in self.tree_dupes.get_children():
            self.tree_dupes.delete(fila)
        self.estado.set(
            f"Duplicados eliminados: {len(resultado['registros'])}. "
            f"Errores: {len(resultado['errores'])}."
        )
        self._escanear()

    def _deshacer(self):
        resultado = core.deshacer()
        if not resultado["ok"]:
            messagebox.showinfo("ArkivX", resultado["mensaje"])
            return
        sesion = resultado["sesion"]
        mensaje = (f"Sesión deshecha ({sesion['tipo']} del {sesion['fecha']}): "
                   f"{len(resultado['revertidos'])} archivos revertidos.")
        if resultado["notas"]:
            mensaje += "\n\n" + "\n".join(resultado["notas"])
        if resultado["errores"]:
            mensaje += (f"\n\n{len(resultado['errores'])} archivos no se "
                        "pudieron revertir.")
        messagebox.showinfo("ArkivX", mensaje)
        self.estado.set(mensaje.split("\n")[0])
        self._escanear()


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
