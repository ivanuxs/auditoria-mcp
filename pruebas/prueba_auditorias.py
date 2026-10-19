#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prueba de las auditorías reales a través del proxy.

Uso:
    .venv/bin/python pruebas/prueba_auditorias.py
"""

import asyncio
import json
import sys
from pathlib import Path

import aiohttp

RAIZ = Path(__file__).resolve().parent.parent
ENV = RAIZ / ".env"
PROTOCOLO = "2025-06-18"
CLIENTE = {"name": "prueba-auditorias", "version": "1.0"}
DOMINIO = "mcp.hlquantlabs.trade"
CORREO = "hlquantlabs.trade"
URL = "https://example.com"

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


def extraer(datos: dict) -> dict:
    resultado = datos.get("result") or {}
    estructurado = resultado.get("structuredContent")
    if isinstance(estructurado, dict):
        return estructurado
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
    tiempo = aiohttp.ClientTimeout(total=120, sock_connect=10, sock_read=120)
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
            for herramienta in ("auditar_dominio", "auditar_correo", "auditar_web"):
                comprobar(herramienta in nombres, f"tools/list incluye {herramienta}")

        async def llamar(nombre: str, argumentos: dict, ident: int) -> dict:
            async with http.post(endpoint, headers=cabeceras, json={
                    "jsonrpc": "2.0", "id": ident, "method": "tools/call",
                    "params": {"name": nombre, "arguments": argumentos}}) as respuesta:
                return await leer_jsonrpc(respuesta)

        print(f"== auditar_dominio {DOMINIO} ==")
        datos = await llamar("auditar_dominio", {"dominio": DOMINIO}, 10)
        resultado = extraer(datos)
        comprobar(not (datos.get("result") or {}).get("isError"),
                  "auditar_dominio no devuelve isError")
        comprobar(resultado.get("dominio") == DOMINIO,
                  f"devuelve el dominio auditado ({resultado.get('dominio')})")
        comprobar(bool(resultado.get("tls")), "incluye el bloque TLS")
        comprobar("dns" in resultado, "incluye el bloque DNS")

        print(f"== auditar_correo {CORREO} ==")
        datos = await llamar("auditar_correo", {"dominio": CORREO}, 11)
        resultado = extraer(datos)
        comprobar(not (datos.get("result") or {}).get("isError"),
                  "auditar_correo no devuelve isError")
        comprobar("mx" in resultado, "incluye MX")
        comprobar("spf" in resultado, "incluye SPF")
        comprobar("dmarc" in resultado, "incluye DMARC")
        comprobar(bool(resultado.get("hallazgos")), "incluye hallazgos")

        print(f"== auditar_web {URL} ==")
        datos = await llamar("auditar_web", {"url": URL}, 12)
        resultado = extraer(datos)
        comprobar(not (datos.get("result") or {}).get("isError"),
                  "auditar_web no devuelve isError")
        comprobar(isinstance(resultado.get("estado"), int),
                  f"devuelve un estado HTTP ({resultado.get('estado')})")
        comprobar("seguridad" in (resultado.get("cabeceras") or {}),
                  "incluye cabeceras de seguridad")
        comprobar("robots" in resultado, "incluye robots.txt")

        print("== rechazo de SSRF ==")
        datos = await llamar("auditar_web", {"url": "http://127.0.0.1"}, 13)
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
