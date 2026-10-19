#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prueba de la herramienta `captura` a través del proxy de auditoría.

Uso:
    .venv/bin/python pruebas/prueba_captura.py
"""

import asyncio
import base64
import json
import sys
from pathlib import Path

import aiohttp

RAIZ = Path(__file__).resolve().parent.parent
ENV = RAIZ / ".env"
PROTOCOLO = "2025-06-18"
CLIENTE = {"name": "prueba-captura", "version": "1.0"}

FALLOS = 0


def comprobar(condicion: bool, descripcion: str) -> None:
    global FALLOS
    if condicion:
        print(f"✔ {descripcion}")
    else:
        FALLOS += 1
        print(f"✘ {descripcion}")


def cargar_env(ruta: Path = ENV) -> dict:
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


async def leer_jsonrpc(respuesta: aiohttp.ClientResponse) -> dict:
    tipo = respuesta.headers.get("Content-Type", "")
    if "text/event-stream" in tipo:
        async for linea in respuesta.content:
            texto = linea.decode("utf-8", "replace").strip()
            if texto.startswith("data:"):
                return json.loads(texto[5:].strip())
        raise RuntimeError("respuesta SSE sin datos")
    return await respuesta.json()


def extraer_texto(resultado: dict) -> dict:
    for parte in resultado.get("content", []):
        if parte.get("type") == "text":
            try:
                return json.loads(parte.get("text", ""))
            except json.JSONDecodeError:
                continue
    return {}


async def main() -> int:
    env = cargar_env()
    token = env.get("MCP_TOKEN", "").strip()
    puerto = env.get("MCP_PROXY_PUERTO", "8941").strip() or "8941"
    if not token:
        print("✘ Falta MCP_TOKEN en el .env.")
        return 2

    endpoint = f"http://127.0.0.1:{puerto}/mcp"
    tiempo = aiohttp.ClientTimeout(total=180, sock_connect=10, sock_read=180)
    cabeceras = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    async with aiohttp.ClientSession(timeout=tiempo) as http:
        async with http.post(endpoint, headers=cabeceras, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": PROTOCOLO,
                           "capabilities": {}, "clientInfo": CLIENTE}}) as respuesta:
            sesion = respuesta.headers.get("Mcp-Session-Id")
            await leer_jsonrpc(respuesta)
        if not sesion:
            print("✘ initialize no devolvió sesión.")
            return 1
        cabeceras["Mcp-Session-Id"] = sesion
        async with http.post(endpoint, headers=cabeceras, json={
                "jsonrpc": "2.0", "method": "notifications/initialized"}) as respuesta:
            await respuesta.read()

        print("== tools/list ==")
        async with http.post(endpoint, headers=cabeceras, json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) as respuesta:
            datos = await leer_jsonrpc(respuesta)
            nombres = [t.get("name") for t in (datos.get("result") or {}).get("tools", [])]
            comprobar("captura" in nombres, "tools/list incluye captura")

        print("== captura de example.com ==")
        async with http.post(endpoint, headers=cabeceras, json={
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "captura",
                           "arguments": {"url": "https://example.com",
                                         "completa": False}}}) as respuesta:
            datos = await leer_jsonrpc(respuesta)
        resultado = datos.get("result") or {}
        comprobar(not resultado.get("isError"), "captura no devuelve isError")

        imagen = ""
        mime = ""
        for parte in resultado.get("content", []):
            if parte.get("type") == "image" and parte.get("data"):
                imagen = parte["data"]
                mime = parte.get("mimeType", "")
                break
        comprobar(bool(imagen), "devuelve un bloque de imagen")
        comprobar(mime.startswith("image/"), f"mime de imagen ({mime})")
        comprobar(len(imagen) > 1000, f"imagen con contenido ({len(imagen)} bytes base64)")
        if imagen:
            try:
                crudo = base64.b64decode(imagen, validate=True)
                comprobar(len(crudo) > 500, f"PNG decodificado ({len(crudo)} bytes)")
            except ValueError:
                comprobar(False, "la imagen es base64 válido")

        metadatos = extraer_texto(resultado)
        comprobar(bool(metadatos.get("url")), "incluye metadatos de la URL")
        comprobar(metadatos.get("bytes", 0) > 0, "incluye el tamaño de la imagen")

        print("== rechazo de SSRF ==")
        async with http.post(endpoint, headers=cabeceras, json={
                "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                "params": {"name": "captura",
                           "arguments": {"url": "http://127.0.0.1"}}}) as respuesta:
            datos = await leer_jsonrpc(respuesta)
        resultado = datos.get("result") or {}
        comprobar(bool(resultado.get("isError")) or bool(datos.get("error")),
                  "rechaza una IP privada/loopback")

    print()
    if FALLOS:
        print(f"✘ {FALLOS} comprobación(es) fallida(s).")
        return 1
    print("✔ Todas las comprobaciones pasaron.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n· Prueba cancelada.")
        sys.exit(130)
