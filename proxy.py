#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""proxy.py — Puerta con token del servidor MCP de auditoría.

**Qué hace.** Escucha en `0.0.0.0:<MCP_PROXY_PUERTO>` (para que nginx de `oficina-2`
pueda alcanzarlo) y reenvía todo a `127.0.0.1:<MCP_INTERNO_PUERTO>`, donde vive el
servidor MCP de auditoría. Sin `Authorization: Bearer <MCP_TOKEN>` (o el de Nodit) no
se reenvía **nada**: 401.

**Dos tokens.** `MCP_TOKEN` es el general y `MCP_TOKEN_NODIT` el exclusivo de Agent
PayGate. Cualquiera de los dos abre la puerta; el de Nodit se revoca quitando su línea
del `.env` y reiniciando.

**Por qué existe.** El servidor MCP no trae autenticación. Si se expone tal cual,
cualquiera que descubra el puerto puede ejecutar auditorías en esta máquina.

**Streaming.** El transporte MCP (Streamable HTTP) puede responder con SSE y mantener la
conexión abierta; por eso se reenvía por trozos y **no** se bufferiza la respuesta.

Uso:
    ./.venv/bin/python proxy.py
"""

import asyncio
import hmac
import sys
from pathlib import Path

import aiohttp
from aiohttp import web

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from utils_logging import imprimir  # noqa: E402

ENV = RAIZ / ".env"

# Cabeceras que no se reenvían al interno (las gestiona aiohttp o son secretas).
NO_REENVIAR = {
    "host", "content-length", "connection", "accept-encoding",
    "authorization", "x-api-key", "cookie",
}


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
# Un token para los agentes actuales y otro exclusivo para Nodit. Ambos valen; así el
# de Nodit se puede revocar sin dejar fuera a los demás.
TOKENS = [
    valor
    for valor in (
        ENV_DATOS.get("MCP_TOKEN", "").strip(),
        ENV_DATOS.get("MCP_TOKEN_NODIT", "").strip(),
    )
    if valor
]
PUERTO = int(ENV_DATOS.get("MCP_PROXY_PUERTO", "8931"))
INTERNO = f"http://127.0.0.1:{ENV_DATOS.get('MCP_INTERNO_PUERTO', '8930')}"

SESION = None


def enmascarar(texto: str) -> str:
    """Tapa cualquier valor del `.env` que aparezca en un mensaje.

    Se aplica a **todo** lo que se registra: es la única forma de no olvidarse.
    """
    for valor in ENV_DATOS.values():
        if valor and len(valor) >= 6:
            texto = texto.replace(valor, valor[:2] + "…****")
    return texto


def registrar(mensaje: str) -> None:
    imprimir(enmascarar(mensaje))


def token_valido(cabecera: str) -> bool:
    """Compara contra todos los tokens válidos en tiempo constante.

    Con `!=` el tiempo de respuesta depende de cuántos caracteres coinciden, y eso
    permite adivinar el token poco a poco. `compare_digest` siempre tarda lo mismo.
    Se compara en bytes porque con `str` no admite caracteres no ASCII. No se sale
    en el primer acierto: se comparan todos para no filtrar cuál coincidió.
    """
    if not TOKENS:
        return False
    recibido = cabecera.encode("utf-8", "replace")
    valido = False
    for token in TOKENS:
        esperado = f"Bearer {token}".encode("utf-8")
        valido |= hmac.compare_digest(recibido, esperado)
    return valido


async def manejar(peticion: web.Request) -> web.StreamResponse:
    """Valida el token y reenvía la petición al MCP interno."""
    if not token_valido(peticion.headers.get("Authorization", "")):
        registrar(f"[proxy] 401 {peticion.remote} {peticion.method} {peticion.path}")
        return web.Response(status=401, text="Falta el token.\n")

    destino = INTERNO + peticion.path_qs
    cuerpo = await peticion.read()
    cabeceras = {clave: valor for clave, valor in peticion.headers.items()
                 if clave.lower() not in NO_REENVIAR}

    try:
        async with SESION.request(peticion.method, destino,
                                  headers=cabeceras, data=cuerpo or None) as respuesta:
            salida = web.StreamResponse(status=respuesta.status)
            for clave, valor in respuesta.headers.items():
                if clave.lower() in {"content-length", "transfer-encoding", "connection"}:
                    continue
                salida.headers[clave] = valor
            await salida.prepare(peticion)
            async for trozo in respuesta.content.iter_any():
                await salida.write(trozo)
            await salida.write_eof()
            registrar(f"[proxy] {peticion.method} {peticion.path} → {respuesta.status}")
            return salida
    except aiohttp.ClientError as error:
        registrar(f"[proxy] el MCP interno no responde: {type(error).__name__}: {error}")
        return web.Response(status=502, text="El servidor MCP no responde.\n")


async def main() -> None:
    global SESION
    if not TOKENS:
        registrar("[proxy] ERROR: falta MCP_TOKEN en el .env. No se arranca.")
        raise SystemExit(2)

    # Sin límite de tiempo total: las respuestas SSE pueden durar minutos.
    SESION = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=None))

    app = web.Application(client_max_size=64 * 1024 * 1024)
    app.router.add_route("*", "/{ruta:.*}", manejar)

    corredor = web.AppRunner(app)
    await corredor.setup()
    await web.TCPSite(corredor, "0.0.0.0", PUERTO).start()
    registrar(f"[proxy] escuchando en 0.0.0.0:{PUERTO} → {INTERNO}")

    try:
        await asyncio.Event().wait()
    finally:
        await SESION.close()
        await corredor.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        registrar("[proxy] cerrado a mano.")
