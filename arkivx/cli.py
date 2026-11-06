"""Interfaz de línea de comandos de ArkivX (en español).

Uso:
    python -m arkivx.cli scan <carpeta> [--json]
    python -m arkivx.cli dupes <carpeta> [--json]
    python -m arkivx.cli organize <carpeta> [--dry-run | --apply]
    python -m arkivx.cli trash-dupes <carpeta> [--apply]
    python -m arkivx.cli undo
    python -m arkivx.cli historial

Nada se mueve ni se elimina sin --apply: por defecto todo es simulación.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import core


def _errores(errores) -> None:
    for error in errores or []:
        print(f"  ⚠ Omitido: {error['ruta']} — {error['error']}", file=sys.stderr)


def cmd_scan(args) -> int:
    resultado = core.escanear(args.carpeta)
    if args.json:
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return 0
    print(f"Carpeta: {resultado['carpeta']}")
    print(f"Archivos: {resultado['total_archivos']}  "
          f"Tamaño total: {core.formato_tamano(resultado['total_bytes'])}")
    print("\nPor categoría:")
    for categoria in core.ORDEN_CATEGORIAS:
        datos = resultado["por_categoria"][categoria]
        if datos["archivos"]:
            print(f"  {categoria:<14} {datos['archivos']:>5} archivos   "
                  f"{core.formato_tamano(datos['bytes'])}")
    print("\nPor extensión (mayor a menor tamaño):")
    for ext, datos in resultado["por_extension"].items():
        print(f"  {ext:<10} {datos['archivos']:>5} archivos   "
              f"{core.formato_tamano(datos['bytes'])}")
    _errores(resultado["errores"])
    return 0


def cmd_dupes(args) -> int:
    resultado = core.encontrar_duplicados(args.carpeta)
    if args.json:
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return 0
    _mostrar_duplicados(resultado)
    _errores(resultado["errores"])
    return 0


def _mostrar_duplicados(resultado) -> None:
    print(f"Carpeta: {resultado['carpeta']}")
    if not resultado["grupos"]:
        print("No se encontraron duplicados. 🎉")
        return
    for i, grupo in enumerate(resultado["grupos"], 1):
        tamano = core.formato_tamano(grupo["tamano"])
        print(f"\nGrupo {i}: {len(grupo['archivos'])} copias de {tamano} "
              f"(se recuperan {core.formato_tamano(grupo['espacio_recuperable'])})")
        for archivo in grupo["archivos"]:
            marca = "✓ conservar" if archivo["ruta"] == grupo["conservar"] \
                else "✗ candidato"
            print(f"  {marca:<12} {archivo['ruta']}")
    print(f"\nGrupos de duplicados: {resultado['total_grupos']}  "
          f"Espacio recuperable: "
          f"{core.formato_tamano(resultado['espacio_recuperable'])}")


def cmd_organize(args) -> int:
    plan = core.plan_organizar(args.carpeta)
    if not plan["movimientos"]:
        print("No hay archivos sueltos que organizar en la raíz de la carpeta.")
        _errores(plan["errores"])
        return 0
    print(f"Plan de organización para: {plan['carpeta']}")
    for mov in plan["movimientos"]:
        print(f"  [{mov['categoria']}] {mov['origen']}  ->  {mov['destino']}")
    print(f"\nTotal: {len(plan['movimientos'])} archivos.")
    _errores(plan["errores"])
    if not args.apply:
        print("\nSIMULACIÓN: no se movió nada. "
              "Para aplicar el plan: organize <carpeta> --apply")
        return 0
    resultado = core.aplicar_plan(plan)
    print(f"\n✔ Aplicado: {len(resultado['movimientos'])} archivos movidos.")
    _errores(resultado["errores"])
    if resultado["sesion"]:
        print(f"Sesión registrada en el historial (id {resultado['sesion']['id']}). "
              "Se puede revertir con: undo")
    return 0


def cmd_trash_dupes(args) -> int:
    resultado = core.encontrar_duplicados(args.carpeta)
    _mostrar_duplicados(resultado)
    _errores(resultado["errores"])
    if not resultado["grupos"]:
        return 0
    if not args.apply:
        print("\nSIMULACIÓN: no se eliminó nada. Los archivos marcados como "
              "«candidato» son los que se eliminarían.")
        print("Para eliminarlos: trash-dupes <carpeta> --apply "
              "(irán a la Papelera si send2trash está instalado; si no, "
              "a la cuarentena de ~/.arkivx).")
        return 0
    salida = core.eliminar_duplicados(resultado)
    print(f"\n✔ Eliminados: {len(salida['registros'])} duplicados.")
    for registro in salida["registros"]:
        if registro["metodo"] == "papelera":
            print(f"  Papelera:    {registro['origen']}")
        else:
            print(f"  Cuarentena:  {registro['origen']}  ->  {registro['destino']}")
    _errores(salida["errores"])
    if salida["sesion"]:
        print(f"Sesión registrada en el historial (id {salida['sesion']['id']}).")
    return 0


def cmd_undo(args) -> int:
    resultado = core.deshacer()
    if not resultado["ok"]:
        print(resultado["mensaje"])
        return 0
    sesion = resultado["sesion"]
    print(f"Sesión deshecha: {sesion['tipo']} del {sesion['fecha']} "
          f"(id {sesion['id']}).")
    for rev in resultado["revertidos"]:
        print(f"  ↩ {rev['de']}  ->  {rev['a']}")
    for nota in resultado["notas"]:
        print(f"  ⚠ {nota}")
    _errores(resultado["errores"])
    print(f"Total revertido: {len(resultado['revertidos'])} archivos.")
    return 0


def cmd_historial(args) -> int:
    historial = core.cargar_historial()
    if not historial["sesiones"]:
        print("El historial está vacío.")
        return 0
    for sesion in historial["sesiones"]:
        estado = "deshecha" if sesion.get("deshecha") else "activa"
        print(f"  [{estado}] {sesion['fecha']}  {sesion['tipo']:<10} "
              f"{len(sesion.get('movimientos', []))} movimientos  "
              f"carpeta: {sesion.get('carpeta')}  (id {sesion['id']})")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="arkivx",
        description="ArkivX — organiza tus archivos y limpia duplicados. "
                    "Cada archivo en su lugar.",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("scan", help="Diagnóstico de una carpeta.")
    p.add_argument("carpeta")
    p.add_argument("--json", action="store_true", help="Salida en JSON.")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("dupes", help="Buscar duplicados por contenido.")
    p.add_argument("carpeta")
    p.add_argument("--json", action="store_true", help="Salida en JSON.")
    p.set_defaults(func=cmd_dupes)

    p = sub.add_parser("organize",
                       help="Organizar por tipo (simulación por defecto).")
    p.add_argument("carpeta")
    grupo = p.add_mutually_exclusive_group()
    grupo.add_argument("--dry-run", dest="apply", action="store_false",
                       help="Solo mostrar el plan (por defecto).")
    grupo.add_argument("--apply", dest="apply", action="store_true",
                       help="Aplicar el plan de movimientos.")
    p.set_defaults(func=cmd_organize, apply=False)

    p = sub.add_parser("trash-dupes",
                       help="Eliminar duplicados (simulación por defecto).")
    p.add_argument("carpeta")
    p.add_argument("--apply", action="store_true",
                   help="Eliminar los candidatos (Papelera o cuarentena).")
    p.set_defaults(func=cmd_trash_dupes)

    p = sub.add_parser("undo", help="Deshacer la última sesión.")
    p.set_defaults(func=cmd_undo)

    p = sub.add_parser("historial", help="Ver el historial de sesiones.")
    p.set_defaults(func=cmd_historial)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
