"""SMTP efímero in-process reutilizable por los tests de integración (Items 047 y 056).

Servidor SMTP mínimo y real (protocolo SMTP sobre loopback en un puerto
efímero) implementado con la stdlib (``socketserver``) en el mismo proceso: sin
dependencias externas ni contenedores, como el sshd ephemeral del Item 037.
Captura remitente, destinatario, autenticación y mensajes para que los tests
verifiquen lo que ODIN entrega sin depender de una casilla real.

Se extrajo de ``tests/test_notify_integration.py`` al llegar el Item 056, que
necesita el mismo catcher para los ciclos del scheduler.
"""

from __future__ import annotations

import base64
import email
import socket
import socketserver
import threading
from email import policy


def b64(text: str) -> str:
    """Codifica ``text`` en base64 ASCII (desafíos de ``AUTH LOGIN``)."""
    return base64.b64encode(text.encode("ascii")).decode("ascii")


class _SmtpHandler(socketserver.StreamRequestHandler):
    """Sesión SMTP mínima: EHLO, AUTH LOGIN, MAIL/RCPT, DATA y QUIT."""

    server: SmtpCatcher

    def handle(self) -> None:
        try:
            self._serve()
        except (OSError, ValueError) as exc:
            self.server.errors.append(exc)

    def _serve(self) -> None:
        self._reply("220 odin-test ESMTP")
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            parts = raw.decode("ascii", "replace").strip().split(" ", 1)
            verb = parts[0].upper()
            argument = parts[1] if len(parts) > 1 else ""
            if verb in ("EHLO", "HELO"):
                self._reply("250-odin-test")
                self._reply("250-AUTH LOGIN")
                self._reply("250 OK")
            elif verb == "AUTH":
                self._auth(argument)
            elif verb in ("MAIL", "RCPT"):
                target = self._address(argument)
                if verb == "MAIL":
                    self.server.senders.append(target)
                else:
                    self.server.recipients.append(target)
                self._reply("250 OK")
            elif verb == "DATA":
                self._reply("354 End data with <CR><LF>.<CR><LF>")
                self.server.messages.append(self._read_data())
                self._reply("250 OK")
            elif verb == "QUIT":
                self._reply("221 Bye")
                return
            else:
                self._reply("250 OK")

    def _auth(self, argument: str) -> None:
        """Acepta ``AUTH LOGIN`` con respuesta inicial o por desafío."""
        pieces = argument.split()
        if not pieces or pieces[0].upper() != "LOGIN":
            self._reply("504 Unrecognized authentication type")
            return
        if len(pieces) > 1:
            username = self._decode(pieces[1])
        else:
            self._reply(f"334 {b64('Username:')}")
            username = self._decode(self._read_auth_value())
        self._reply(f"334 {b64('Password:')}")
        password = self._decode(self._read_auth_value())
        self.server.auth.append((username, password))
        self._reply("235 Authentication successful")

    def _read_auth_value(self) -> str:
        return self.rfile.readline().decode("ascii", "replace").strip()

    def _read_data(self) -> str:
        lines: list[bytes] = []
        while True:
            line = self.rfile.readline()
            if not line or line in (b".\r\n", b".\n"):
                break
            lines.append(line)
        return b"".join(lines).decode("utf-8", "replace")

    @staticmethod
    def _address(argument: str) -> str:
        """Extrae la dirección de ``MAIL FROM:<...>``/``RCPT TO:<...>``."""
        _, _, address = argument.partition(":")
        return address.strip().strip("<>")

    @staticmethod
    def _decode(value: str) -> str:
        return base64.b64decode(value).decode("utf-8", "replace")

    def _reply(self, text: str) -> None:
        self.wfile.write(f"{text}\r\n".encode("ascii"))


class SmtpCatcher(socketserver.ThreadingTCPServer):
    """Servidor SMTP efímero en un hilo: captura lo que ODIN entrega."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _SmtpHandler)
        self.messages: list[str] = []
        self.senders: list[str] = []
        self.recipients: list[str] = []
        self.auth: list[tuple[str, str]] = []
        self.errors: list[BaseException] = []
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    def close(self) -> None:
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=5)


def parse_message(raw: str) -> email.message.Message:
    """Parsea el mensaje capturado decodificando cabeceras/cuerpo MIME."""
    return email.message_from_string(raw, policy=policy.default)


def closed_port() -> int:
    """Reserva y libera un puerto loopback: la conexión será rechazada."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
