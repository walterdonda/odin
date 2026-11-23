"""Tests unitarios del finder de ``pg_dump`` (ticket 03, §2.5 y §2.6).

Espejo de ``test_gbak_finder.py`` con la regla de versión del engine
PostgreSQL: entre las rutas típicas versionadas (el major está en la ruta)
solo se aceptan majors ≥ 18 y gana el mayor; si ninguna instalación
versionada llega a 18, ``find_pg_dump`` cae a las rutas sin versión en el
nombre —las típicas (``/usr/bin/pg_dump``, ``/usr/local/pgsql/bin``) y cada
entrada del ``PATH`` (la regla "Siempre" de §2.6)— y la primera que existe
alcanza; recién entonces devuelve ``None``. Para las rutas sin versión basta
la existencia (sin verificación de versión en runtime, regla documentada en
§2.5).
"""

import unittest
from pathlib import Path
from unittest.mock import patch

from odin.pg_dump_finder import find_pg_dump


class TestPgDumpFinder(unittest.TestCase):
    @patch("pathlib.Path.glob")
    @patch("os.path.exists")
    @patch("sys.platform", "linux")
    def test_linux_versioned_mayor_gana(self, mock_exists, mock_glob):
        # Debian/Ubuntu con 17, 18 y 19 instalados: gana el 19 y se ignoran
        # los majors < 18.
        mock_glob.side_effect = lambda *args: (
            [
                Path("/usr/lib/postgresql/19"),
                Path("/usr/lib/postgresql/18"),
                Path("/usr/lib/postgresql/17"),
            ]
            if args[-1] == "*"
            else []
        )
        mock_exists.side_effect = lambda path: Path(path).as_posix().startswith(
            "/usr/lib/postgresql/"
        )

        found = find_pg_dump()

        self.assertEqual(found.as_posix(), "/usr/lib/postgresql/19/bin/pg_dump")

    @patch("pathlib.Path.glob")
    @patch("os.path.exists")
    @patch("sys.platform", "linux")
    def test_linux_pgdg_route(self, mock_exists, mock_glob):
        # PGDG yum (§2.6): /usr/pgsql-<major>/bin/pg_dump.
        mock_glob.side_effect = lambda *args: (
            [Path("/usr/pgsql-18")] if args[-1] == "pgsql-*" else []
        )
        mock_exists.side_effect = lambda path: (
            Path(path).as_posix() == "/usr/pgsql-18/bin/pg_dump"
        )

        found = find_pg_dump()

        self.assertEqual(found.as_posix(), "/usr/pgsql-18/bin/pg_dump")

    @patch("pathlib.Path.glob")
    @patch("os.path.exists")
    @patch("sys.platform", "linux")
    def test_solo_majors_17_sin_binario_en_path_devuelve_none(self, mock_exists, mock_glob):
        # Solo instalaciones ≤ 17 y nada en las rutas sin versión: el finder
        # devuelve None (equivale a "binario no encontrado").
        mock_glob.side_effect = lambda *args: (
            [Path("/usr/lib/postgresql/17"), Path("/usr/lib/postgresql/15")]
            if args[-1] == "*"
            else []
        )
        mock_exists.side_effect = lambda path: Path(path).as_posix().startswith(
            "/usr/lib/postgresql/"
        )

        with patch.dict("os.environ", {"PATH": ""}):
            found = find_pg_dump()

        self.assertIsNone(found)

    @patch("pathlib.Path.glob")
    @patch("os.path.exists")
    @patch("sys.platform", "linux")
    def test_majors_17_caen_a_una_entrada_del_path(self, mock_exists, mock_glob):
        # Ninguna instalación versionada llega a 18, pero hay un pg_dump en el
        # PATH: la regla "Siempre" de §2.6 lo usa antes de rendirse.
        mock_glob.side_effect = lambda *args: (
            [Path("/usr/lib/postgresql/17"), Path("/usr/lib/postgresql/15")]
            if args[-1] == "*"
            else []
        )
        mock_exists.side_effect = lambda path: (
            Path(path).as_posix() == "/opt/pg/bin/pg_dump"
            or Path(path).as_posix().startswith("/usr/lib/postgresql/")
        )

        with patch.dict("os.environ", {"PATH": "/opt/other:/opt/pg/bin"}):
            found = find_pg_dump()

        self.assertEqual(found.as_posix(), "/opt/pg/bin/pg_dump")

    @patch("pathlib.Path.glob")
    @patch("os.path.exists")
    @patch("sys.platform", "linux")
    def test_major_18_gana_sobre_una_entrada_del_path(self, mock_exists, mock_glob):
        # Instalación versionada ≥ 18 presente: gana sobre cualquier binario
        # del PATH (el fallback a rutas sin versión no se consulta).
        mock_glob.side_effect = lambda *args: (
            [Path("/usr/lib/postgresql/18")] if args[-1] == "*" else []
        )
        mock_exists.return_value = True

        with patch.dict("os.environ", {"PATH": "/opt/pg/bin"}):
            found = find_pg_dump()

        self.assertEqual(found.as_posix(), "/usr/lib/postgresql/18/bin/pg_dump")

    @patch("pathlib.Path.glob", return_value=[])
    @patch("os.path.exists")
    @patch("sys.platform", "linux")
    def test_linux_wrapper_sin_instalaciones_versionadas(self, mock_exists, mock_glob):
        # Sin carpetas versionadas, /usr/bin/pg_dump (wrapper de Debian o
        # ruta de Fedora) alcanza: para las rutas sin versión basta existir.
        mock_exists.side_effect = lambda path: Path(path).as_posix() == "/usr/bin/pg_dump"

        with patch.dict("os.environ", {"PATH": "/opt/other"}):
            found = find_pg_dump()

        self.assertEqual(found.as_posix(), "/usr/bin/pg_dump")

    @patch("pathlib.Path.glob", return_value=[])
    @patch("os.path.exists")
    @patch("sys.platform", "linux")
    def test_linux_source_route(self, mock_exists, mock_glob):
        # Instalación desde fuente (§2.6): /usr/local/pgsql/bin/pg_dump.
        mock_exists.side_effect = lambda path: (
            Path(path).as_posix() == "/usr/local/pgsql/bin/pg_dump"
        )

        with patch.dict("os.environ", {"PATH": "/opt/other"}):
            found = find_pg_dump()

        self.assertEqual(found.as_posix(), "/usr/local/pgsql/bin/pg_dump")

    @patch("pathlib.Path.glob", return_value=[])
    @patch("os.path.exists")
    @patch("sys.platform", "linux")
    def test_path_entry(self, mock_exists, mock_glob):
        # "Siempre" de §2.6: cada entrada del PATH + pg_dump, al final de la
        # lista de candidatos.
        mock_exists.side_effect = lambda path: Path(path).as_posix() == "/opt/pg/bin/pg_dump"

        with patch.dict("os.environ", {"PATH": "/opt/other:/opt/pg/bin"}):
            found = find_pg_dump()

        self.assertEqual(found.as_posix(), "/opt/pg/bin/pg_dump")

    @patch("pathlib.Path.glob")
    @patch("os.path.exists")
    @patch("sys.platform", "win32")
    def test_windows_versioned_route_mayor_gana(self, mock_exists, mock_glob):
        # C:\Program Files\PostgreSQL\<major>\bin\pg_dump.exe (§2.6): gana el
        # 18 ante el 17. Comparación por ``as_posix`` para pasar en ambos
        # hosts.
        mock_glob.return_value = [
            Path("C:/Program Files/PostgreSQL/17"),
            Path("C:/Program Files/PostgreSQL/18"),
        ]
        mock_exists.return_value = True

        with patch.dict("os.environ", {"PATH": "C:\\other"}):
            found = find_pg_dump()

        self.assertIsNotNone(found)
        self.assertTrue(str(found).endswith("pg_dump.exe"))
        self.assertEqual(found.as_posix(), "C:/Program Files/PostgreSQL/18/bin/pg_dump.exe")

    @patch("pathlib.Path.glob", return_value=[])
    @patch("os.path.exists")
    @patch("sys.platform", "linux")
    def test_not_found(self, mock_exists, mock_glob):
        mock_exists.return_value = False

        with patch.dict("os.environ", {"PATH": "/opt/other"}):
            found = find_pg_dump()

        self.assertIsNone(found)


if __name__ == "__main__":
    unittest.main()
