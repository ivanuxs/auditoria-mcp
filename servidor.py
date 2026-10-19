#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Servidor MCP de auditoría web y de correo.

Escucha **solo** en `127.0.0.1`; la puerta pública es el proxy con token.
En esta fase (1) expone `estado` para validar el esqueleto. Las auditorías
reales (dominio, correo, web y captura) llegan en la fase 2.

Uso:
    ./.venv/bin/python servidor.py
"""

from pathlib import Path

from mcp.server.mcpserver import MCPServer

RAIZ = Path(__file__).resolve().parent
ENV = RAIZ / ".env"

VERSION = "0.1.0"


def cargar_env(ruta: Path = ENV) -> dict:
    """Lee el `.env` sin dependencias externas."""
    datos = {}
    try:
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            datos[clave.strip()] = valor.strip().strip('"').strip("'")
    except OSError:
        pass
    return datos


ENV_DATOS = cargar_env()
PUERTO = int(ENV_DATOS.get("MCP_INTERNO_PUERTO", "8940"))

SERVIDOR = MCPServer(
    name="auditoria",
    title="Auditoría web y de correo",
    description="Auditorías deterministas de dominio, DNS, TLS, correo y web.",
    version=VERSION,
)


@SERVIDOR.tool()
def estado() -> dict:
    """Devuelve el estado del servicio de auditoría."""
    return {
        "servicio": "auditoria",
        "version": VERSION,
        "estado": "ok",
    }


def main() -> None:
    """Arranca el transporte Streamable HTTP en loopback."""
    SERVIDOR.run(transport="streamable-http", host="127.0.0.1", port=PUERTO)


if __name__ == "__main__":
    main()
