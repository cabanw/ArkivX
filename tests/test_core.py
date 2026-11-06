"""Pruebas del motor de ArkivX (solo biblioteca estándar).

Ejecutar desde la raíz del repositorio:
    python -m unittest discover -s tests -v
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arkivx import cli, core  # noqa: E402


class BaseTemporal(unittest.TestCase):
    """Carpeta temporal con un HOME falso y sin send2trash."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name).resolve()
        self.home = base / "home"
        self.home.mkdir()
        self.trabajo = base / "trabajo"
        self.trabajo.mkdir()
        parches = [
            mock.patch.object(Path, "home", return_value=self.home),
            mock.patch.dict(sys.modules, {"send2trash": None}),
        ]
        for parche in parches:
            parche.start()
            self.addCleanup(parche.stop)
        self.addCleanup(self._tmp.cleanup)

    def escribir(self, relativo, contenido=b"hola"):
        ruta = self.trabajo / relativo
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(contenido)
        return ruta


class TestDuplicados(BaseTemporal):
    def test_archivos_vacios_no_son_duplicados(self):
        self.escribir("a/__init__.py", b"")
        self.escribir("b/__init__.py", b"")
        resultado = core.encontrar_duplicados(self.trabajo)
        self.assertEqual(resultado["total_grupos"], 0)

    def test_detecta_duplicados_reales(self):
        self.escribir("x.txt", b"igual")
        self.escribir("sub/x.txt", b"igual")
        resultado = core.encontrar_duplicados(self.trabajo)
        self.assertEqual(resultado["total_grupos"], 1)
        self.assertEqual(resultado["grupos"][0]["conservar"],
                         str(self.trabajo / "x.txt"))

    def test_omite_carpetas_de_dependencias_y_ocultas(self):
        self.escribir("node_modules/pkg/LICENSE", b"MIT")
        self.escribir(".git/objects/abc", b"MIT")
        self.escribir("AppData/cfg.json", b"MIT")
        self.escribir("LICENSE", b"MIT")
        resultado = core.encontrar_duplicados(self.trabajo)
        self.assertEqual(resultado["total_grupos"], 0)
        omitidas = {Path(o["ruta"]).name for o in resultado["omitidas"]}
        self.assertTrue({"node_modules", ".git", "AppData"} <= omitidas)

    def test_omite_desktop_ini(self):
        self.escribir("a/desktop.ini", b"[.ShellClassInfo]")
        self.escribir("b/desktop.ini", b"[.ShellClassInfo]")
        self.assertEqual(
            core.encontrar_duplicados(self.trabajo)["total_grupos"], 0)

    def test_enlace_simbolico_no_cuenta_como_duplicado(self):
        real = self.escribir("carpeta/larga/real.bin", b"datos")
        enlace = self.trabajo / "e.bin"
        try:
            os.symlink(real, enlace)
        except (OSError, NotImplementedError):
            self.skipTest("Sin permiso para crear enlaces simbólicos")
        resultado = core.encontrar_duplicados(self.trabajo)
        self.assertEqual(resultado["total_grupos"], 0)

    def test_no_elimina_si_la_copia_conservada_cambio(self):
        conservar = self.escribir("x.txt", b"igual")
        candidato = self.escribir("sub/x.txt", b"igual")
        resultado = core.encontrar_duplicados(self.trabajo)
        conservar.unlink()  # el usuario la borró entre análisis y limpieza
        salida = core.eliminar_duplicados(resultado)
        self.assertEqual(salida["registros"], [])
        self.assertTrue(candidato.exists())

    def test_no_elimina_candidato_modificado(self):
        self.escribir("x.txt", b"igual")
        candidato = self.escribir("sub/x.txt", b"igual")
        resultado = core.encontrar_duplicados(self.trabajo)
        candidato.write_bytes(b"otra")  # mismo tamaño, contenido distinto
        salida = core.eliminar_duplicados(resultado)
        self.assertEqual(salida["registros"], [])
        self.assertTrue(candidato.exists())

    def test_cuarentena_y_deshacer(self):
        self.escribir("x.txt", b"igual")
        candidato = self.escribir("sub/x.txt", b"igual")
        salida = core.eliminar_duplicados(
            core.encontrar_duplicados(self.trabajo))
        self.assertEqual(len(salida["registros"]), 1)
        self.assertFalse(candidato.exists())
        resultado = core.deshacer()
        self.assertTrue(resultado["completa"])
        self.assertTrue(candidato.exists())


class TestOrganizar(BaseTemporal):
    def test_plan_omite_archivos_de_sistema_y_ocultos(self):
        self.escribir("desktop.ini", b"x")
        self.escribir(".gitignore", b"x")
        self.escribir("~$doc.docx", b"x")
        self.escribir("foto.jpg", b"x")
        plan = core.plan_organizar(self.trabajo)
        nombres = [Path(m["origen"]).name for m in plan["movimientos"]]
        self.assertEqual(nombres, ["foto.jpg"])

    def test_archivo_con_nombre_de_categoria(self):
        self.escribir("Documentos", b"soy un archivo")
        self.escribir("a.pdf", b"pdf")
        plan = core.plan_organizar(self.trabajo)
        self.assertNotIn("a.pdf",
                         [Path(m["origen"]).name for m in plan["movimientos"]])
        self.assertTrue(any("Documentos" in e["error"]
                            for e in plan["errores"]))

    def test_aplicar_y_deshacer(self):
        origen = self.escribir("foto.jpg", b"x")
        resultado = core.aplicar_plan(core.plan_organizar(self.trabajo))
        self.assertEqual(len(resultado["movimientos"]), 1)
        self.assertFalse(origen.exists())
        core.deshacer()
        self.assertTrue(origen.exists())
        self.assertFalse((self.trabajo / "Imágenes").exists())

    def test_deshacer_parcial_se_puede_reintentar(self):
        a = self.escribir("a.jpg", b"a")
        b = self.escribir("b.jpg", b"b")
        core.aplicar_plan(core.plan_organizar(self.trabajo))
        movimiento_real = core.shutil.move
        llamadas = {"n": 0}

        def falla_una_vez(origen, destino):
            llamadas["n"] += 1
            if llamadas["n"] == 1:
                raise PermissionError("en uso")
            return movimiento_real(origen, destino)

        with mock.patch.object(core.shutil, "move", side_effect=falla_una_vez):
            primero = core.deshacer()
        self.assertFalse(primero["completa"])
        self.assertEqual(len(primero["revertidos"]), 1)
        segundo = core.deshacer()
        self.assertTrue(segundo["completa"])
        self.assertTrue(a.exists() and b.exists())


class TestHistorial(BaseTemporal):
    def test_historial_danado_se_respalda(self):
        ruta = core.ruta_historial()
        ruta.write_text("{esto no es json", encoding="utf-8")
        self.assertEqual(core.cargar_historial(), {"sesiones": []})
        respaldos = list(ruta.parent.glob("historial.danado-*.json"))
        self.assertEqual(len(respaldos), 1)

    def test_guardado_atomico_sin_temporales(self):
        core.registrar_sesion({"id": "1", "tipo": "x", "fecha": "",
                               "movimientos": [], "deshecha": True})
        ruta = core.ruta_historial()
        self.assertEqual(len(json.loads(ruta.read_text("utf-8"))["sesiones"]), 1)
        self.assertFalse(ruta.with_name(ruta.name + ".tmp").exists())


class TestGuard(BaseTemporal):
    def test_bloquea_home_y_su_padre(self):
        self.assertTrue(core.es_carpeta_protegida(self.home))
        self.assertTrue(core.es_carpeta_protegida(self.home.parent))

    def test_bloquea_raiz(self):
        self.assertTrue(core.es_carpeta_protegida(Path(self.trabajo.anchor)))

    def test_carpeta_de_usuario_llamada_recovery_no_se_bloquea(self):
        carpeta = self.trabajo / "Recovery"
        carpeta.mkdir()
        self.assertFalse(core.es_carpeta_protegida(carpeta))
        core.escanear(carpeta)  # no lanza

    @unittest.skipUnless(os.name == "nt", "solo Windows")
    def test_bloquea_windows_y_subcarpetas(self):
        raiz_sistema = os.environ.get("SystemRoot", r"C:\Windows")
        self.assertTrue(core.es_carpeta_protegida(raiz_sistema))
        self.assertTrue(core.es_carpeta_protegida(
            os.path.join(raiz_sistema, "Temp")))

    def test_enlace_a_carpeta_del_sistema_se_bloquea(self):
        objetivo = (os.environ.get("SystemRoot", r"C:\Windows")
                    if os.name == "nt" else "/etc")
        enlace = self.trabajo / "atajo"
        try:
            os.symlink(objetivo, enlace, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Sin permiso para crear enlaces simbólicos")
        with self.assertRaises(ValueError):
            core.escanear(enlace)


class TestCuarentenaUnidad(BaseTemporal):
    def test_misma_unidad_usa_cuarentena_principal(self):
        self.assertEqual(core.carpeta_cuarentena(self.trabajo),
                         self.home / ".arkivx" / "cuarentena")


class TestCli(unittest.TestCase):
    def test_errores_con_clave_origen_no_revienta(self):
        salida = io.StringIO()
        with redirect_stderr(salida):
            cli._errores([{"origen": "x", "error": "e"},
                          {"ruta": "y", "error": "e"}])
        self.assertIn("x", salida.getvalue())
        self.assertIn("y", salida.getvalue())


if __name__ == "__main__":
    unittest.main()
