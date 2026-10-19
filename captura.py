#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cliente del MCP navegador para tomar capturas de pantalla.

Se conecta al proxy del proyecto `../navegador/` con un token dedicado y usa
`browser_navigate` + `browser_take_screenshot`. No comparte el token general.
"""

from __future__ import annotations

import asyncio
import base64
import json
import struct
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp

from auditorias import ErrorAuditoria, _verificar_publico, normalizar_url

RAIZ = Path(__file__).resolve().parent
ENV = RAIZ / ".env"
PROTOCOLO = "2025-06-18"
CLIENTE = {"name": "auditoria-captura", "version": "1.0"}
TIEMPO = 120.0


def _cargar_env(ruta: Path = ENV) -> dict:
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


def _url_navegador(valor: str) -> str:
    """Acepta la base o el endpoint completo y devuelve siempre .../mcp."""
    url = (valor or "").strip() or "http://127.0.0.1:8931/mcp"
    return url.rstrip("/") if url.rstrip("/").endswith("/mcp") else url.rstrip("/") + "/mcp"


async def _leer_jsonrpc(respuesta: aiohttp.ClientResponse) -> dict:
    tipo = respuesta.headers.get("Content-Type", "")
    if "text/event-stream" in tipo:
        async for linea in respuesta.content:
            texto = linea.decode("utf-8", "replace").strip()
            if texto.startswith("data:"):
                return json.loads(texto[5:].strip())
        raise ErrorAuditoria("El navegador no devolvió datos.")
    return await respuesta.json()


def _dimensiones_png(datos: bytes) -> dict:
    if len(datos) >= 24 and datos[:8] == b"\x89PNG\r\n\x1a\n":
        ancho, alto = struct.unpack(">II", datos[16:24])
        return {"ancho": ancho, "alto": alto}
    return {}


async def capturar(url: str, completa: bool = True) -> dict:
    """Navega a una URL pública y devuelve una captura PNG en bytes."""
    inicial = normalizar_url(url)
    partes = urlsplit(inicial)
    await _verificar_publico(partes.hostname or "")

    env = _cargar_env()
    endpoint = _url_navegador(env.get("NAVEGADOR_URL", ""))
    token = env.get("NAVEGADOR_TOKEN", "").strip()
    if not token:
        raise ErrorAuditoria("Falta NAVEGADOR_TOKEN en el .env de auditoría.")

    cabeceras = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    tiempo = aiohttp.ClientTimeout(total=TIEMPO, sock_connect=10, sock_read=TIEMPO)

    async with aiohttp.ClientSession(timeout=tiempo) as http:
        try:
            async with http.post(endpoint, headers=cabeceras, json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": PROTOCOLO,
                               "capabilities": {}, "clientInfo": CLIENTE}}) as respuesta:
                sesion = respuesta.headers.get("Mcp-Session-Id")
                await _leer_jsonrpc(respuesta)
            if not sesion:
                raise ErrorAuditoria("El navegador no abrió sesión.")
            cabeceras["Mcp-Session-Id"] = sesion

            async with http.post(endpoint, headers=cabeceras, json={
                    "jsonrpc": "2.0", "method": "notifications/initialized"}) as respuesta:
                await respuesta.read()

            async def llamar(nombre: str, argumentos: dict, ident: int) -> dict:
                async with http.post(endpoint, headers=cabeceras, json={
                        "jsonrpc": "2.0", "id": ident, "method": "tools/call",
                        "params": {"name": nombre, "arguments": argumentos}}) as respuesta:
                    datos = await _leer_jsonrpc(respuesta)
                resultado = datos.get("result") or {}
                if resultado.get("isError"):
                    texto = " ".join(
                        parte.get("text", "")
                        for parte in resultado.get("content", [])
                        if parte.get("type") == "text"
                    )
                    raise ErrorAuditoria(
                        f"El navegador falló en {nombre}: {texto[:200]}")
                if "error" in datos:
                    raise ErrorAuditoria(f"El navegador devolvió error en {nombre}.")
                return resultado

            await llamar("browser_navigate", {"url": inicial}, 2)
            resultado = await llamar("browser_take_screenshot", {
                "fullPage": bool(completa), "type": "png"}, 3)
        except aiohttp.ClientError as error:
            raise ErrorAuditoria(
                f"No se pudo contactar al MCP navegador: {type(error).__name__}") from error
        finally:
            try:
                async with http.post(endpoint, headers=cabeceras, json={
                        "jsonrpc": "2.0", "id": 9, "method": "tools/call",
                        "params": {"name": "browser_close", "arguments": {}}}) as respuesta:
                    await respuesta.read()
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass

    imagen = ""
    mime = ""
    nota = ""
    for parte in resultado.get("content", []):
        if parte.get("type") == "image" and parte.get("data") and not imagen:
            imagen = parte["data"]
            mime = parte.get("mimeType", "image/png")
        elif parte.get("type") == "text" and not nota:
            nota = parte.get("text", "")

    if not imagen:
        raise ErrorAuditoria("El navegador no devolvió una imagen.")
    try:
        datos = base64.b64decode(imagen, validate=True)
    except ValueError as error:
        raise ErrorAuditoria("La imagen devuelta no es base64 válido.") from error

    return {
        "url": inicial,
        "completa": bool(completa),
        "formato": "png",
        "mime": mime or "image/png",
        "bytes": len(datos),
        "dimensiones": _dimensiones_png(datos),
        "nota": nota,
        "imagen": datos,
    }
