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


class TestProyectos(BaseTemporal):
    """Caso real: dos versiones de un proyecto y una solución de Power
    Platform descomprimida dos veces. Nada dentro debe eliminarse."""

    def test_copias_de_proyecto_nunca_son_candidatas(self):
        for v in ("v1", "v2"):
            self.escribir(f"MCP/{v}/requirements.txt", b"x" if v == "v1" else b"y")
            self.escribir(f"MCP/{v}/skills/narrative.json", b"{narrativa}")
            self.escribir(f"MCP/{v}/README.md", b"# leeme")
        resultado = core.encontrar_duplicados(self.trabajo)
        self.assertGreater(resultado["total_grupos"], 0)
        self.assertEqual(resultado["total_candidatos"], 0)
        salida = core.eliminar_duplicados(resultado)
        self.assertEqual(salida["registros"], [])

    def test_solucion_power_platform_protegida(self):
        for v in ("1_0_0_1", "1_0_0_5"):
            self.escribir(f"Agente_{v}/[Content_Types].xml", b"<Types/>")
            self.escribir(f"Agente_{v}/solution.xml", b"<s/>")
            self.escribir(f"Agente_{v}/env/def.xml", b"<def/>")
        self.assertEqual(
            core.encontrar_duplicados(self.trabajo)["total_candidatos"], 0)

    def test_marcador_git_aunque_la_carpeta_se_omita(self):
        for v in ("a", "b"):
            (self.trabajo / v / ".git").mkdir(parents=True)
            self.escribir(f"{v}/main.py", b"print(1)")
        self.assertEqual(
            core.encontrar_duplicados(self.trabajo)["total_candidatos"], 0)

    def test_copia_suelta_si_se_elimina_y_la_del_proyecto_no(self):
        self.escribir("proyecto/package.json", b"{}")
        dentro = self.escribir("proyecto/logo.png", b"PNG")
        suelta1 = self.escribir("logo.png", b"PNG")
        suelta2 = self.escribir("descargas/logo (1).png", b"PNG")
        resultado = core.encontrar_duplicados(self.trabajo)
        grupo = [g for g in resultado["grupos"] if g["tamano"] == 3][0]
        self.assertEqual(grupo["conservar"], str(suelta1))
        self.assertEqual(grupo["candidatos"], [str(suelta2)])
        core.eliminar_duplicados(resultado)
        self.assertTrue(dentro.exists() and suelta1.exists())
        self.assertFalse(suelta2.exists())

    def test_no_organiza_una_carpeta_que_es_proyecto(self):
        self.escribir("package.json", b"{}")
        self.escribir("index.js", b"1")
        with self.assertRaises(ValueError):
            core.plan_organizar(self.trabajo)


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


class TestDiscoExterno(BaseTemporal):
    """Raíz de un disco de datos, copias de seguridad, Lightroom y RAW."""

    @unittest.skipUnless(os.name == "nt", "solo Windows")
    def test_raiz_de_disco_de_datos_solo_lectura(self):
        raiz = self.trabajo.anchor
        with mock.patch.object(core, "_unidad_sistema", return_value="z:"):
            self.assertTrue(core.es_raiz_unidad_datos(raiz))
            self.assertEqual(core._validar_carpeta(raiz, solo_lectura=True),
                             Path(raiz))
            self.assertEqual(
                core._validar_carpeta(raiz.rstrip("\\"), solo_lectura=True),
                Path(raiz))
            with self.assertRaises(ValueError):
                core._validar_carpeta(raiz)
            with self.assertRaises(ValueError):
                core.plan_organizar(raiz)

    def test_raiz_del_disco_del_sistema_sigue_bloqueada(self):
        raiz = self.trabajo.anchor
        if os.name == "nt":
            with mock.patch.object(core, "_unidad_sistema",
                                   return_value=os.path.normcase(raiz[:2])):
                self.assertFalse(core.es_raiz_unidad_datos(raiz))
                with self.assertRaises(ValueError):
                    core._validar_carpeta(raiz, solo_lectura=True)
        else:
            with self.assertRaises(ValueError):
                core._validar_carpeta(raiz, solo_lectura=True)

    def test_subcarpeta_no_es_raiz_de_datos(self):
        self.assertFalse(core.es_raiz_unidad_datos(self.trabajo))

    def test_windows_image_backup_protegido(self):
        for v in ("a", "b"):
            self.escribir(f"WindowsImageBackup/PC/Backup {v}/disco.vhdx", b"VHD")
        res = core.encontrar_duplicados(self.trabajo)
        self.assertGreater(res["total_grupos"], 0)
        self.assertEqual(res["total_candidatos"], 0)
        destino = self.trabajo / "WindowsImageBackup" / "PC" / "Backup a"
        with self.assertRaises(ValueError):
            core.plan_organizar(destino)
        with self.assertRaises(ValueError):
            core.plan_organizar(self.trabajo / "WindowsImageBackup")

    def test_respaldo_se_sigue_contando_en_escaneo(self):
        self.escribir("WindowsImageBackup/PC/disco.vhdx", b"VHDX")
        res = core.escanear(self.trabajo)
        self.assertEqual(res["total_archivos"], 1)
        self.assertEqual(res["por_categoria"]["Discos virtuales"]["archivos"], 1)

    def test_catalogo_lightroom_protegido(self):
        for v in ("v1", "v2"):
            self.escribir(f"LR/{v}/Catalogo.lrcat", b"cat" + v.encode())
            self.escribir(f"LR/{v}/Catalogo Previews.lrdata/0/a.lrprev", b"PREV")
        self.assertEqual(
            core.encontrar_duplicados(self.trabajo)["total_candidatos"], 0)
        with self.assertRaises(ValueError):
            core.plan_organizar(self.trabajo / "LR" / "v1")
        with self.assertRaises(ValueError):
            core.plan_organizar(self.trabajo / "LR" / "v1" / "Catalogo Previews.lrdata")

    def test_raw_de_camara_son_imagenes(self):
        for ext in (".NEF", ".cr2", ".arw", ".dng"):
            self.assertEqual(core.categoria_de(Path("foto" + ext)), "Imágenes")
        self.assertEqual(core.categoria_de(Path("x.vhdx")), "Discos virtuales")


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
