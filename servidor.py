#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Servidor MCP de auditoría web y de correo.

Escucha **solo** en `127.0.0.1`; la puerta pública es el proxy con token.
Expone `estado`, las auditorías de dominio, DNS, correo y web, la comparación
entre dominios y la captura de pantalla de una URL.

Uso:
    ./.venv/bin/python servidor.py
"""

import json
from pathlib import Path

from mcp.server.mcpserver import Image, MCPServer
from mcp.types import TextContent

from auditorias import (
    ErrorAuditoria,
    auditar_correo as _auditar_correo,
    auditar_dns as _auditar_dns,
    auditar_dominio as _auditar_dominio,
    auditar_web as _auditar_web,
    comparar as _comparar,
)
from captura import capturar as _capturar

RAIZ = Path(__file__).resolve().parent
ENV = RAIZ / ".env"

VERSION = "0.3.0"


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


@SERVIDOR.tool()
async def auditar_dominio(dominio: str) -> dict:
    """Audita DNS, RDAP y TLS de un dominio público.

    Args:
        dominio: Dominio sin esquema, por ejemplo `example.com`.
    """
    try:
        return await _auditar_dominio(dominio)
    except ErrorAuditoria as error:
        raise ValueError(str(error)) from error


@SERVIDOR.tool()
async def auditar_dns(dominio: str) -> dict:
    """Audita CAA, DNSSEC, SOA, CNAME y TTL de un dominio público.

    Args:
        dominio: Dominio sin esquema, por ejemplo `example.com`.
    """
    try:
        return await _auditar_dns(dominio)
    except ErrorAuditoria as error:
        raise ValueError(str(error)) from error


@SERVIDOR.tool()
async def auditar_correo(dominio: str) -> dict:
    """Audita MX, SPF, DMARC, DKIM, MTA-STS y BIMI de un dominio público.

    Args:
        dominio: Dominio sin esquema, por ejemplo `example.com`.
    """
    try:
        return await _auditar_correo(dominio)
    except ErrorAuditoria as error:
        raise ValueError(str(error)) from error


@SERVIDOR.tool()
async def comparar(dominios: str) -> dict:
    """Compara de 2 a 5 dominios y los ordena de peor a mejor.

    Args:
        dominios: Lista separada por comas, por ejemplo `uno.pe,dos.pe`.
    """
    try:
        return await _comparar(dominios)
    except ErrorAuditoria as error:
        raise ValueError(str(error)) from error


@SERVIDOR.tool()
async def auditar_web(url: str) -> dict:
    """Audita estado, redirecciones, cabeceras y cookies de una URL pública.

    Args:
        url: URL http o https; si no lleva esquema se asume https.
    """
    try:
        return await _auditar_web(url)
    except ErrorAuditoria as error:
        raise ValueError(str(error)) from error


@SERVIDOR.tool()
async def captura(url: str, completa: bool = True) -> list[TextContent | Image]:
    """Toma una captura de pantalla de una URL pública.

    Args:
        url: URL http o https; si no lleva esquema se asume https.
        completa: true para capturar toda la página; false, solo la ventana.
    """
    try:
        resultado = await _capturar(url, completa=completa)
    except ErrorAuditoria as error:
        raise ValueError(str(error)) from error

    metadatos = {clave: valor for clave, valor in resultado.items() if clave != "imagen"}
    return [
        TextContent(type="text", text=json.dumps(metadatos, ensure_ascii=False, indent=2)),
        Image(data=resultado["imagen"], format="png"),
    ]


def main() -> None:
    """Arranca el transporte Streamable HTTP en loopback."""
    SERVIDOR.run(transport="streamable-http", host="127.0.0.1", port=PUERTO)


if __name__ == "__main__":
    main()
