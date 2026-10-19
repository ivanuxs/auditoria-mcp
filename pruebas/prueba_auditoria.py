#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prueba de punta a punta del MCP de auditoría.

Comprueba:
  1. Sin token: 401.
  2. `initialize` abre sesión con `Mcp-Session-Id` y viaja como SSE.
  3. `tools/list` incluye `estado`.
  4. `tools/call` de `estado` devuelve un resultado correcto.

Uso:
    .venv/bin/python pruebas/prueba_auditoria.py
"""

import asyncio
import json
import sys
from pathlib import Path

import aiohttp

RAIZ = Path(__file__).resolve().parent.parent
ENV = RAIZ / ".env"
PROTOCOLO = "2025-06-18"
CLIENTE = {"name": "prueba-auditoria", "version": "1.0"}

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


async def main() -> int:
    env = cargar_env()
    token = env.get("MCP_TOKEN", "").strip()
    puerto = env.get("MCP_PROXY_PUERTO", "8941").strip() or "8941"
    if not token:
        print("✘ Falta MCP_TOKEN en el .env: no se puede probar.")
        return 2

    endpoint = f"http://127.0.0.1:{puerto}/mcp"
    tiempo = aiohttp.ClientTimeout(total=60, sock_connect=10, sock_read=60)

    async with aiohttp.ClientSession(timeout=tiempo) as http:
        print("== 1) sin token ==")
        async with http.post(endpoint, headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": PROTOCOLO,
                                 "capabilities": {}, "clientInfo": CLIENTE}}) as respuesta:
            comprobar(respuesta.status == 401,
                      f"sin token responde 401 (HTTP {respuesta.status})")

        cabeceras = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        print("== 2) initialize ==")
        async with http.post(endpoint, headers=cabeceras, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": PROTOCOLO,
                           "capabilities": {}, "clientInfo": CLIENTE}}) as respuesta:
            sesion = respuesta.headers.get("Mcp-Session-Id")
            tipo = respuesta.headers.get("Content-Type", "")
            largo = respuesta.headers.get("Content-Length")
            datos = await leer_jsonrpc(respuesta)
            comprobar(respuesta.status == 200,
                      f"initialize responde 200 (HTTP {respuesta.status})")
            comprobar(bool(sesion), "initialize devuelve Mcp-Session-Id")
            comprobar("text/event-stream" in tipo, f"initialize viaja como SSE ({tipo})")
            comprobar(largo is None, "initialize no trae Content-Length")
            comprobar(bool(datos.get("result")), "initialize devuelve resultado JSON-RPC")

        if not sesion:
            print("✘ Sin sesión no se puede continuar.")
            return 1

        cabeceras["Mcp-Session-Id"] = sesion

        async with http.post(endpoint, headers=cabeceras, json={
                "jsonrpc": "2.0", "method": "notifications/initialized"}) as respuesta:
            await respuesta.read()
            comprobar(respuesta.status in (200, 202, 204),
                      f"notifications/initialized responde {respuesta.status}")

        print("== 3) tools/list ==")
        async with http.post(endpoint, headers=cabeceras, json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) as respuesta:
            datos = await leer_jsonrpc(respuesta)
            nombres = [t.get("name") for t in (datos.get("result") or {}).get("tools", [])]
            comprobar("estado" in nombres, "tools/list incluye estado")
            comprobar(respuesta.status == 200, f"tools/list responde 200 (HTTP {respuesta.status})")

        print("== 4) tools/call estado ==")
        async with http.post(endpoint, headers=cabeceras, json={
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "estado", "arguments": {}}}) as respuesta:
            datos = await leer_jsonrpc(respuesta)
            resultado = (datos.get("result") or {})
            comprobar(respuesta.status == 200,
                      f"tools/call responde 200 (HTTP {respuesta.status})")
            comprobar(not resultado.get("isError"), "tools/call no devuelve isError")

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
