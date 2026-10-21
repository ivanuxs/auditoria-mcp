#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Auditorías deterministas de dominio, correo y web.

No usa IA: solo DNS, RDAP, TLS y HTTP. Todas las entradas se validan y se
comprueba que el destino resuelva a direcciones públicas, para evitar SSRF.

Las funciones públicas son:

- `auditar_dominio(dominio)`
- `auditar_correo(dominio)`
- `auditar_web(url)`
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import ssl
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit

import aiohttp
import dns.asyncresolver
import dns.exception
import dns.flags
import dns.resolver

TIEMPO_DNS = 6.0
TIEMPO_HTTP = 15.0
MAX_REDIRECCIONES = 8
MAX_TXT = 20
MAX_CUERPO = 512 * 1024
AGENTE = "mcp-auditoria/0.3 (+https://auditoria.hlquantlabs.trade)"
DOMINIO_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$",
    re.IGNORECASE,
)
SELECTORES_DKIM = (
    "default", "google", "selector1", "selector2", "k1", "mail", "dkim", "s1", "s2",
)


class ErrorAuditoria(ValueError):
    """Entrada inválida o destino no permitido."""


# ---------------------------------------------------------------------------
# Validación y red
# ---------------------------------------------------------------------------


def normalizar_dominio(valor: str) -> str:
    """Devuelve el dominio en ASCII, sin esquema, ruta, puerto ni punto final."""
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorAuditoria("El dominio está vacío.")

    texto = valor.strip().lower().rstrip(".")
    if "://" in texto:
        texto = urlsplit(texto).hostname or ""
    if "/" in texto:
        texto = texto.split("/", 1)[0]
    if "@" in texto:
        texto = texto.rsplit("@", 1)[1]
    if texto.count(":") == 1 and texto.rsplit(":", 1)[1].isdigit():
        texto = texto.rsplit(":", 1)[0]

    try:
        texto = texto.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ErrorAuditoria("Dominio no válido.") from error

    if not DOMINIO_RE.fullmatch(texto):
        raise ErrorAuditoria(f"Dominio no válido: {valor!r}")

    try:
        ipaddress.ip_address(texto)
    except ValueError:
        pass
    else:
        raise ErrorAuditoria("Se esperaba un dominio, no una dirección IP.")

    if texto == "localhost" or texto.endswith((".local", ".internal", ".localhost")):
        raise ErrorAuditoria("Solo se permiten dominios públicos.")

    return texto


def normalizar_url(valor: str) -> str:
    """Normaliza una URL http/https y valida el host."""
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorAuditoria("La URL está vacía.")

    texto = valor.strip()
    if "://" not in texto:
        texto = "https://" + texto

    partes = urlsplit(texto)
    if partes.scheme not in ("http", "https"):
        raise ErrorAuditoria("Solo se admiten http y https.")
    if not partes.hostname:
        raise ErrorAuditoria("La URL no tiene host.")

    host = normalizar_dominio(partes.hostname)
    try:
        puerto = partes.port
    except ValueError as error:
        raise ErrorAuditoria("Puerto no válido.") from error

    netloc = host if puerto in (None, 80, 443) else f"{host}:{puerto}"
    return urlunsplit((partes.scheme, netloc, partes.path or "/", partes.query, ""))


def _resolutor() -> dns.asyncresolver.Resolver:
    resolutor = dns.asyncresolver.Resolver(configure=True)
    resolutor.timeout = 4.0
    resolutor.lifetime = TIEMPO_DNS
    return resolutor


async def _consultar(nombre: str, tipo: str) -> list[str]:
    """Consulta DNS y devuelve los registros como texto; [] si no hay."""
    registros, _ = await _consultar_detalle(nombre, tipo)
    return registros


def _registros(respuesta, tipo: str) -> list[str]:
    """Convierte una respuesta DNS en texto, con los TXT ya concatenados."""
    if tipo == "TXT":
        return [
            b"".join(registro.strings).decode("utf-8", "replace")
            for registro in respuesta
            if getattr(registro, "strings", None) is not None
        ]
    return [str(registro).rstrip(".") for registro in respuesta]


async def _consultar_detalle(nombre: str, tipo: str) -> tuple[list[str], int | None]:
    """Consulta DNS y devuelve (registros, TTL); ([], None) si no hay."""
    try:
        respuesta = await _resolutor().resolve(nombre, tipo, raise_on_no_answer=False)
    except dns.exception.DNSException:
        return [], None
    if respuesta.rrset is None:
        return [], None
    return _registros(respuesta, tipo), int(respuesta.rrset.ttl)


async def _validado_dnssec(nombre: str) -> bool:
    """True si el resolutor pudo validar DNSSEC (bandera AD)."""
    try:
        resolutor = _resolutor()
        resolutor.use_edns(0, want_dnssec=True)
        respuesta = await resolutor.resolve(nombre, "A", raise_on_no_answer=False)
    except (dns.exception.DNSException, AttributeError):
        return False
    if respuesta.response is None:
        return False
    return bool(respuesta.response.flags & dns.flags.AD)


async def _verificar_publico(host: str) -> list[str]:
    """Resuelve el host y rechaza cualquier dirección no pública."""
    host = normalizar_dominio(host)
    direcciones: list[str] = []
    for tipo in ("A", "AAAA"):
        direcciones.extend(await _consultar(host, tipo))

    if not direcciones:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None)
        except OSError as error:
            raise ErrorAuditoria(f"No se pudo resolver {host}.") from error
        direcciones = [info[4][0] for info in infos]

    publicas: list[str] = []
    for direccion in direcciones:
        try:
            ip = ipaddress.ip_address(direccion.split("%", 1)[0])
        except ValueError:
            continue
        if (
            not ip.is_global
            or ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ErrorAuditoria(f"{host} apunta a una dirección no pública ({ip}).")
        publicas.append(str(ip))

    if not publicas:
        raise ErrorAuditoria(f"{host} no tiene direcciones públicas.")
    return sorted(set(publicas))


def _campo_certificado(campo) -> str:
    for rdn in campo or ():
        for clave, valor in rdn:
            if clave == "commonName":
                return valor
    return ""


def _fecha_certificado(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromtimestamp(ssl.cert_time_to_seconds(valor), tz=timezone.utc)
    except (KeyError, ValueError, OverflowError):
        return None


def _certificado(host: str, puerto: int = 443) -> dict:
    """Obtiene el certificado TLS. Es bloqueante: se llama en un hilo."""
    contexto = ssl.create_default_context()
    try:
        with socket.create_connection((host, puerto), timeout=8) as crudo:
            with contexto.wrap_socket(crudo, server_hostname=host) as tls:
                cert = tls.getpeercert()
                version = tls.version()
                cifrado = tls.cipher()
    except (OSError, ssl.SSLError, ValueError) as error:
        return {"valido": False, "error": f"{type(error).__name__}: {error}"}

    vence = _fecha_certificado(cert.get("notAfter"))
    ahora = datetime.now(tz=timezone.utc)
    dias = (vence - ahora).days if vence else None
    return {
        "valido": True,
        "sujeto": _campo_certificado(cert.get("subject")),
        "emisor": _campo_certificado(cert.get("issuer")),
        "desde": (_fecha_certificado(cert.get("notBefore")) or "").isoformat()
        if _fecha_certificado(cert.get("notBefore")) else "",
        "vence": vence.isoformat() if vence else "",
        "dias_restantes": dias,
        "san": [valor for tipo, valor in cert.get("subjectAltName", ()) if tipo == "DNS"],
        "version": version or "",
        "cifrado": cifrado[0] if cifrado else "",
    }


def _nombre_entidad(entidad: dict) -> str:
    vcard = entidad.get("vcardArray")
    if isinstance(vcard, list) and len(vcard) == 2:
        for item in vcard[1]:
            if isinstance(item, list) and len(item) >= 4 and item[0] == "fn":
                return str(item[3])
    return str(entidad.get("handle") or "")


def _registrador(datos: dict) -> str:
    for entidad in datos.get("entities", []):
        if "registrar" in (entidad.get("roles") or []):
            nombre = _nombre_entidad(entidad)
            if nombre:
                return nombre
    return ""


async def _rdap(dominio: str) -> dict:
    """Consulta RDAP; si el TLD no lo soporta, lo indica sin romper la auditoría."""
    url = f"https://rdap.org/domain/{dominio}"
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as sesion:
            async with sesion.get(
                url,
                headers={"User-Agent": AGENTE,
                         "Accept": "application/rdap+json, application/json"},
            ) as respuesta:
                if respuesta.status != 200:
                    return {"disponible": False, "http": respuesta.status}
                datos = await respuesta.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
        return {"disponible": False, "error": type(error).__name__}

    eventos = {
        evento.get("eventAction"): evento.get("eventDate")
        for evento in datos.get("events", [])
        if evento.get("eventAction")
    }
    return {
        "disponible": True,
        "registro": eventos.get("registration", ""),
        "vencimiento": eventos.get("expiration", ""),
        "ultimo_cambio": eventos.get("last changed", ""),
        "registrador": _registrador(datos),
        "estado": datos.get("status", []),
        "nameservers": [
            servidor.get("ldhName", "")
            for servidor in datos.get("nameservers", [])
            if servidor.get("ldhName")
        ],
    }


def _parsear_mx(registros: list[str]) -> list[dict]:
    salida = []
    for registro in registros:
        partes = registro.split()
        if len(partes) == 2 and partes[0].isdigit():
            salida.append({"prioridad": int(partes[0]), "host": partes[1]})
        else:
            salida.append({"prioridad": None, "host": registro})
    return sorted(salida, key=lambda item: (item["prioridad"] is None, item["prioridad"] or 0))


def _analizar_spf(registro: str) -> dict:
    partes = registro.split()
    return {
        "registro": registro,
        "todos": next(
            (parte for parte in partes if parte in ("+all", "-all", "~all", "?all")), ""
        ),
        "include": [parte[8:] for parte in partes if parte.startswith("include:")],
        "redirect": next(
            (parte[9:] for parte in partes if parte.startswith("redirect=")), ""
        ),
    }


def _analizar_dmarc(registro: str) -> dict:
    etiquetas: dict[str, str] = {}
    for parte in registro.split(";"):
        if "=" in parte:
            clave, valor = parte.split("=", 1)
            etiquetas[clave.strip().lower()] = valor.strip()
    return {
        "registro": registro,
        "politica": etiquetas.get("p", ""),
        "subdominios": etiquetas.get("sp", ""),
        "rua": etiquetas.get("rua", ""),
        "ruf": etiquetas.get("ruf", ""),
        "pct": etiquetas.get("pct", ""),
    }


async def _obtener_texto(url: str, limite: int = MAX_CUERPO) -> tuple[int, str]:
    partes = urlsplit(url)
    try:
        await _verificar_publico(partes.hostname or "")
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=TIEMPO_HTTP),
            connector=aiohttp.TCPConnector(ssl=False),
            headers={"User-Agent": AGENTE},
        ) as sesion:
            async with sesion.get(url, allow_redirects=True) as respuesta:
                cuerpo = await respuesta.content.read(limite)
                return respuesta.status, cuerpo.decode("utf-8", "replace")
    except (ErrorAuditoria, aiohttp.ClientError, asyncio.TimeoutError):
        return 0, ""


# ---------------------------------------------------------------------------
# Auditorías
# ---------------------------------------------------------------------------


def _nota(hallazgos: list[dict]) -> dict:
    """Calificación de la A a la F con reglas fijas a partir de los hallazgos."""
    altos = sum(1 for h in hallazgos if h.get("nivel") == "alto")
    medios = sum(1 for h in hallazgos if h.get("nivel") == "medio")
    informativos = sum(1 for h in hallazgos if h.get("nivel") == "info")
    puntos = max(0, 100 - 25 * altos - 10 * medios)
    letra = ("A" if puntos >= 90 else "B" if puntos >= 75 else
             "C" if puntos >= 60 else "D" if puntos >= 40 else "F")
    return {
        "letra": letra,
        "puntos": puntos,
        "altos": altos,
        "medios": medios,
        "informativos": informativos,
    }


def _algoritmos(registros: list[str]) -> list[str]:
    """Números de algoritmo DNSSEC presentes en registros DS/DNSKEY."""
    salida = set()
    for registro in registros:
        partes = registro.split()
        if len(partes) >= 3 and partes[2].isdigit():
            salida.add(partes[2])
    return sorted(salida)


async def auditar_dominio(dominio: str) -> dict:
    """Audita DNS, RDAP y TLS de un dominio público."""
    nombre = normalizar_dominio(dominio)

    a = await _consultar(nombre, "A")
    aaaa = await _consultar(nombre, "AAAA")
    ips = await _verificar_publico(nombre) if (a or aaaa) else []

    mx = _parsear_mx(await _consultar(nombre, "MX"))
    ns = await _consultar(nombre, "NS")
    txt = (await _consultar(nombre, "TXT"))[:MAX_TXT]

    if ips:
        tls, rdap = await asyncio.gather(
            asyncio.to_thread(_certificado, nombre),
            _rdap(nombre),
        )
    else:
        tls = {"valido": False, "error": "El dominio no tiene direcciones A/AAAA."}
        rdap = await _rdap(nombre)

    hallazgos = []
    if not a and not aaaa:
        hallazgos.append({"nivel": "alto",
                          "mensaje": "El dominio no resuelve a ninguna dirección."})
    if not mx:
        hallazgos.append({"nivel": "info",
                          "mensaje": "No hay registros MX: el dominio no recibe correo."})
    if not ns:
        hallazgos.append({"nivel": "medio",
                          "mensaje": "No se encontraron servidores NS."})
    if not tls.get("valido"):
        hallazgos.append({"nivel": "alto",
                          "mensaje": f"Certificado TLS no válido: {tls.get('error', '')}"})
    elif tls.get("dias_restantes") is not None and tls["dias_restantes"] <= 30:
        hallazgos.append({"nivel": "medio",
                          "mensaje": f"El certificado vence en {tls['dias_restantes']} días."})
    if not rdap.get("disponible"):
        hallazgos.append({"nivel": "info",
                          "mensaje": "RDAP no disponible para este dominio."})

    return {
        "dominio": nombre,
        "ips": ips,
        "dns": {"a": a, "aaaa": aaaa, "mx": mx, "ns": ns, "txt": txt},
        "tls": tls,
        "rdap": rdap,
        "hallazgos": hallazgos,
        "calificacion": _nota(hallazgos),
    }


async def auditar_dns(dominio: str) -> dict:
    """Audita CAA, DNSSEC, SOA, CNAME y TTL de un dominio público."""
    nombre = normalizar_dominio(dominio)

    a, ttl_a = await _consultar_detalle(nombre, "A")
    aaaa, _ = await _consultar_detalle(nombre, "AAAA")
    if a or aaaa:
        await _verificar_publico(nombre)

    caa = await _consultar(nombre, "CAA")
    soa = await _consultar(nombre, "SOA")
    cname = await _consultar(nombre, "CNAME")
    ns = await _consultar(nombre, "NS")
    ds = await _consultar(nombre, "DS")
    dnskey = await _consultar(nombre, "DNSKEY")

    firmado = bool(ds or dnskey)
    validado = await _validado_dnssec(nombre) if firmado else False

    hallazgos = []
    if not caa:
        hallazgos.append({"nivel": "medio",
                          "mensaje": "Sin CAA: cualquier CA puede emitir "
                                     "certificados para el dominio."})
    if not firmado:
        hallazgos.append({"nivel": "info",
                          "mensaje": "Sin DNSSEC: las respuestas DNS no van firmadas."})
    elif not validado:
        hallazgos.append({"nivel": "info",
                          "mensaje": "DNSSEC firmado, pero este resolutor no "
                                     "confirmó la validación (bandera AD)."})
    if not soa:
        hallazgos.append({"nivel": "medio", "mensaje": "No se encontró registro SOA."})
    if cname:
        hallazgos.append({"nivel": "medio",
                          "mensaje": "Hay CNAME en el nombre raíz; no es lo habitual."})
    if not a and not aaaa:
        hallazgos.append({"nivel": "info",
                          "mensaje": "Sin A/AAAA: el dominio no aloja web, "
                                     "solo DNS o correo."})
    if not ns:
        hallazgos.append({"nivel": "medio", "mensaje": "No se encontraron servidores NS."})

    return {
        "dominio": nombre,
        "caa": caa,
        "dnssec": {
            "firmado": firmado,
            "validado": validado,
            "ds": ds,
            "claves": len(dnskey),
            "algoritmos": _algoritmos(ds + dnskey),
        },
        "soa": soa,
        "cname": cname,
        "ns": ns,
        "ttl_a": ttl_a,
        "hallazgos": hallazgos,
        "calificacion": _nota(hallazgos),
    }


async def auditar_correo(dominio: str) -> dict:
    """Audita MX, SPF, DMARC, DKIM, MTA-STS y BIMI de un dominio público."""
    nombre = normalizar_dominio(dominio)

    mx = _parsear_mx(await _consultar(nombre, "MX"))
    txt = await _consultar(nombre, "TXT")
    spf_registro = next((valor for valor in txt if valor.lower().startswith("v=spf1")), "")
    spf = _analizar_spf(spf_registro) if spf_registro else None

    dmarc_registros = await _consultar(f"_dmarc.{nombre}", "TXT")
    dmarc_registro = next(
        (valor for valor in dmarc_registros if valor.lower().startswith("v=dmarc1")), ""
    )
    dmarc = _analizar_dmarc(dmarc_registro) if dmarc_registro else None

    dkim = []
    for selector in SELECTORES_DKIM:
        registros = await _consultar(f"{selector}._domainkey.{nombre}", "TXT")
        if registros:
            dkim.append({
                "selector": selector,
                "registros": [registro[:200] for registro in registros],
            })

    mta_registros = await _consultar(f"_mta-sts.{nombre}", "TXT")
    mta_politica = ""
    if mta_registros:
        _, mta_politica = await _obtener_texto(
            f"https://mta-sts.{nombre}/.well-known/mta-sts.txt", limite=4096)

    bimi = await _consultar(f"default._bimi.{nombre}", "TXT")

    hallazgos = []
    if not mx:
        hallazgos.append({"nivel": "alto",
                          "mensaje": "No hay MX: el dominio no puede recibir correo."})
    if not spf:
        hallazgos.append({"nivel": "alto", "mensaje": "Falta el registro SPF."})
    elif spf["todos"] in ("+all", "?all"):
        hallazgos.append({"nivel": "alto",
                          "mensaje": f"SPF demasiado permisivo ({spf['todos']})."})
    elif spf["todos"] == "~all":
        hallazgos.append({"nivel": "medio",
                          "mensaje": "SPF usa ~all (softfail); considera -all."})

    if not dmarc:
        hallazgos.append({"nivel": "alto", "mensaje": "Falta el registro DMARC."})
    elif dmarc["politica"] == "none":
        hallazgos.append({"nivel": "medio",
                          "mensaje": "DMARC está en p=none: solo monitoriza."})

    if not dkim:
        hallazgos.append({"nivel": "info",
                          "mensaje": "No se encontró DKIM en los selectores comunes."})
    if not mta_registros:
        hallazgos.append({"nivel": "info", "mensaje": "No hay MTA-STS."})
    if not bimi:
        hallazgos.append({"nivel": "info", "mensaje": "No hay BIMI."})

    return {
        "dominio": nombre,
        "mx": mx,
        "spf": spf,
        "dmarc": dmarc,
        "dkim": dkim,
        "mta_sts": {"registros": mta_registros, "politica": mta_politica},
        "bimi": bimi[:MAX_TXT],
        "hallazgos": hallazgos,
        "calificacion": _nota(hallazgos),
        "nota": "DKIM solo se busca en selectores comunes; puede existir otro.",
    }


def _seguridad(cabeceras: dict[str, str], esquema: str) -> dict:
    claves = {clave.lower(): valor for clave, valor in cabeceras.items()}
    hsts = claves.get("strict-transport-security", "")
    csp = claves.get("content-security-policy", "")
    xcto = claves.get("x-content-type-options", "")
    xfo = claves.get("x-frame-options", "")
    referrer = claves.get("referrer-policy", "")
    permisos = claves.get("permissions-policy", "")
    coop = claves.get("cross-origin-opener-policy", "")

    puntos = 0
    faltantes = []
    if hsts:
        puntos += 20
    else:
        faltantes.append("Strict-Transport-Security")
    if csp:
        puntos += 20
    else:
        faltantes.append("Content-Security-Policy")
    if xcto.lower() == "nosniff":
        puntos += 10
    else:
        faltantes.append("X-Content-Type-Options")
    if xfo or "frame-ancestors" in csp.lower():
        puntos += 10
    else:
        faltantes.append("X-Frame-Options / frame-ancestors")
    if referrer:
        puntos += 10
    else:
        faltantes.append("Referrer-Policy")
    if permisos:
        puntos += 10
    else:
        faltantes.append("Permissions-Policy")
    if coop:
        puntos += 10
    else:
        faltantes.append("Cross-Origin-Opener-Policy")
    if esquema != "https":
        faltantes.append("HTTPS")

    letra = "A" if puntos >= 90 else "B" if puntos >= 75 else "C" if puntos >= 60 else "D" if puntos >= 40 else "F"
    return {
        "hsts": hsts,
        "csp": csp,
        "x_content_type_options": xcto,
        "x_frame_options": xfo,
        "referrer_policy": referrer,
        "permissions_policy": permisos,
        "cross_origin_opener_policy": coop,
        "puntos": puntos,
        "letra": letra,
        "faltantes": faltantes,
    }


def _analizar_cookies(valores: list[str]) -> list[dict]:
    salida = []
    for valor in valores[:20]:
        partes = [parte.strip() for parte in valor.split(";")]
        nombre = partes[0].split("=", 1)[0] if partes else ""
        atributos = {}
        for parte in partes[1:]:
            if "=" in parte:
                clave, contenido = parte.split("=", 1)
                atributos[clave.lower()] = contenido
            else:
                atributos[parte.lower()] = True
        salida.append({
            "nombre": nombre,
            "secure": "secure" in atributos,
            "httponly": "httponly" in atributos,
            "samesite": atributos.get("samesite", ""),
        })
    return salida


async def auditar_web(url: str) -> dict:
    """Audita estado, redirecciones, cabeceras y cookies de una URL pública."""
    inicial = normalizar_url(url)
    partes = urlsplit(inicial)
    await _verificar_publico(partes.hostname or "")

    cadena = []
    final = inicial
    estado_final = 0
    cabeceras_final: dict[str, str] = {}
    cookies_final: list[str] = []
    cuerpo = b""

    conector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=TIEMPO_HTTP),
        connector=conector,
        headers={"User-Agent": AGENTE},
    ) as sesion:
        actual = inicial
        for _ in range(MAX_REDIRECCIONES + 1):
            partes_actuales = urlsplit(actual)
            await _verificar_publico(partes_actuales.hostname or "")
            inicio = time.monotonic()
            async with sesion.get(actual, allow_redirects=False) as respuesta:
                milisegundos = int((time.monotonic() - inicio) * 1000)
                ubicacion = respuesta.headers.get("Location")
                cadena.append({
                    "url": actual,
                    "estado": respuesta.status,
                    "destino": ubicacion or "",
                    "ms": milisegundos,
                })
                if 300 <= respuesta.status < 400 and ubicacion:
                    actual = urljoin(actual, ubicacion)
                    continue
                estado_final = respuesta.status
                cabeceras_final = dict(respuesta.headers)
                cookies_final = respuesta.headers.getall("Set-Cookie", [])
                cuerpo = await respuesta.content.read(MAX_CUERPO)
                final = actual
                break
        else:
            raise ErrorAuditoria("Demasiadas redirecciones.")

    esquema_final = urlsplit(final).scheme
    seguridad = _seguridad(cabeceras_final, esquema_final)
    cookies = _analizar_cookies(cookies_final)

    origen = f"{esquema_final}://{urlsplit(final).netloc}"
    estado_robots, robots = await _obtener_texto(f"{origen}/robots.txt", 128 * 1024)
    estado_sitemap, sitemap = await _obtener_texto(f"{origen}/sitemap.xml", 256 * 1024)

    tls = await asyncio.to_thread(_certificado, urlsplit(final).hostname or "") \
        if esquema_final == "https" else {}

    hallazgos = []
    if estado_final >= 400:
        hallazgos.append({"nivel": "alto",
                          "mensaje": f"La URL final responde HTTP {estado_final}."})
    if esquema_final != "https":
        hallazgos.append({"nivel": "alto", "mensaje": "La URL final no usa HTTPS."})
    if seguridad["faltantes"]:
        hallazgos.append({"nivel": "medio",
                          "mensaje": "Faltan cabeceras: " + ", ".join(seguridad["faltantes"])})
    for cookie in cookies:
        if not cookie["secure"] or not cookie["httponly"]:
            hallazgos.append({"nivel": "medio",
                              "mensaje": f"Cookie {cookie['nombre']!r} sin Secure/HttpOnly."})
    if len(cadena) > 3:
        hallazgos.append({"nivel": "info",
                          "mensaje": f"{len(cadena) - 1} redirecciones antes del destino final."})
    if tls and not tls.get("valido"):
        hallazgos.append({"nivel": "alto",
                          "mensaje": f"Certificado TLS no válido: {tls.get('error', '')}"})

    return {
        "url_inicial": inicial,
        "url_final": final,
        "estado": estado_final,
        "redirecciones": cadena[:-1] if len(cadena) > 1 else [],
        "cabeceras": {
            "servidor": cabeceras_final.get("Server", ""),
            "tipo": cabeceras_final.get("Content-Type", ""),
            "seguridad": seguridad,
        },
        "cookies": cookies,
        "tls": tls,
        "robots": {
            "estado": estado_robots,
            "bytes": len(robots),
            "bloqueos": robots.count("Disallow:"),
            "sitemaps": [
                linea.split(":", 1)[1].strip()
                for linea in robots.splitlines()
                if linea.lower().startswith("sitemap:")
            ][:10],
        },
        "sitemap": {
            "estado": estado_sitemap,
            "urls": sitemap.count("<loc>"),
        },
        "hallazgos": hallazgos,
    }


# ---------------------------------------------------------------------------
# Comparación
# ---------------------------------------------------------------------------

MAX_COMPARAR = 5
LIMITE_COMPARAR = 3


async def comparar(dominios: str) -> dict:
    """Compara de 2 a 5 dominios y los ordena de peor a mejor."""
    lista = [valor.strip() for valor in (dominios or "").split(",") if valor.strip()]
    if len(lista) < 2:
        raise ErrorAuditoria("Indica al menos dos dominios separados por coma.")
    if len(lista) > MAX_COMPARAR:
        raise ErrorAuditoria(f"Máximo {MAX_COMPARAR} dominios por comparación.")

    nombres: list[str] = []
    for valor in lista:
        nombre = normalizar_dominio(valor)
        if nombre in nombres:
            raise ErrorAuditoria(f"Dominio repetido: {nombre}.")
        nombres.append(nombre)

    limite = asyncio.Semaphore(LIMITE_COMPARAR)

    async def revisar(nombre: str) -> dict:
        async with limite:
            try:
                dominio, correo = await asyncio.gather(
                    auditar_dominio(nombre), auditar_correo(nombre))
            except ErrorAuditoria as error:
                return {"dominio": nombre, "error": str(error)}
        hallazgos = (list(dominio.get("hallazgos") or [])
                     + list(correo.get("hallazgos") or []))
        return {
            "dominio": nombre,
            "calificacion": _nota(hallazgos),
            "hallazgos": hallazgos,
            "tls_valido": bool((dominio.get("tls") or {}).get("valido")),
            "mx": len(correo.get("mx") or []),
            "spf": bool(correo.get("spf")),
            "dmarc": bool(correo.get("dmarc")),
        }

    resultados = await asyncio.gather(*(revisar(nombre) for nombre in nombres))
    correctos = [r for r in resultados if "error" not in r]
    correctos.sort(key=lambda r: (r["calificacion"]["puntos"], r["dominio"]))

    return {
        "dominios": resultados,
        "orden": [r["dominio"] for r in correctos],
        "regla": ("Peor primero. Se restan 25 puntos por hallazgo alto y 10 por "
                  "medio; los informativos no restan y el desempate es alfabético."),
    }
