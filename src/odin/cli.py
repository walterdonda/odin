"""Punto de entrada de la CLI de ODIN.

Stub inicial (Item 001): solo expone --version/--help para que el console
script quede operativo. Los subcomandos run/validate/service se agregan en
los items 005-007 del roadmap AIDE.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from odin import __version__


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser raíz de la CLI de ODIN."""
    parser = argparse.ArgumentParser(
        prog="odin",
        description="Respaldo externo de bases de datos Firebird: gbak + 7z + SFTP + correo.",
    )
    parser.add_argument("--version", action="version", version=f"odin {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Ejecuta la CLI; sin argumentos imprime la ayuda y devuelve 0."""
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
