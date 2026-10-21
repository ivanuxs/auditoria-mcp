# mcp/auditoria

Servidor **MCP** que entrega auditorías deterministas de **dominio, DNS, TLS, correo y
web** a agentes de IA, además de comparación entre dominios y capturas de pantalla.

Proyecto hermano de `../navegador/`, con su propio entorno, token, registros y repositorio.

## Estado

- **2026-10-19**: unidad `mcp-auditoria` instalada y habilitada; HTTPS activo con
  Let's Encrypt. El registro DNS está en modo **solo-DNS**, sin proxy de Cloudflare.

---

## Arquitectura

```
Agente
  │  Authorization: Bearer <MCP_TOKEN>
  ▼
DNS de Cloudflare  →  nginx de oficina-2 (auditoria.hlquantlabs.trade)
  │  proxy_pass a 127.0.0.1:8941
  ▼
proxy.py (valida token, 401 si falta)
  │
  ▼
127.0.0.1:8940            ← servidor MCP (SDK oficial mcp 2.3.0)
```

- El MCP escucha **solo** en `127.0.0.1`.
- El proxy escucha en `0.0.0.0:8941`; en el servidor solo lo alcanza nginx por `127.0.0.1`.
- Todo corre inicialmente en **oficina-2**; luego se traslada a un servidor dedicado.

## Qué necesita la máquina

| Pieza | Cómo está en `oficina-2` |
|---|---|
| Python | `.venv` con `mcp==2.3.0` y `aiohttp==3.14.5` |
| Entorno | creado con `python3 -m venv --without-pip` + `get-pip.py` (no hay `python3-venv`) |
| Servicio | unidad `mcp-auditoria.service` (systemd del sistema) |
| Nginx | `nginx/auditoria.hlquantlabs.trade.conf` |

## Arrancar

Con systemd, una vez instalada la unidad:

```bash
sudo cp sistema/mcp-auditoria.service /etc/systemd/system/mcp-auditoria.service
sudo systemctl daemon-reload
sudo systemctl enable --now mcp-auditoria
sudo systemctl status mcp-auditoria
```

A mano, para depurar:

```bash
export PATH=$HOME/.local/node/bin:$PATH
./arrancar.sh          # Ctrl+C o ./parar.sh para cerrar
```

> Con el servicio activo, `./parar.sh` no sirve para apagarlo — systemd lo resucita a los
> 5 s. Se para con `sudo systemctl stop mcp-auditoria`.

## Herramientas

| Herramienta | Qué devuelve |
|---|---|
| `estado` | Versión y estado del servicio |
| `auditar_dominio` | A/AAAA/MX/NS/TXT, RDAP (registrador, alta, vencimiento) y TLS |
| `auditar_dns` | CAA, DNSSEC (firmado/validado), SOA, CNAME, NS y TTL |
| `auditar_correo` | MX, SPF, DMARC, DKIM (selectores comunes), MTA-STS y BIMI |
| `comparar` | De 2 a 5 dominios, ordenados de peor a mejor |
| `auditar_web` | Estado, redirecciones, cabeceras de seguridad, cookies, TLS, robots y sitemap |
| `captura` | Captura de pantalla PNG de una URL pública (imagen + metadatos) |

Todas rechazan IPs, `localhost` y redes privadas para evitar SSRF. Los resultados incluyen
`hallazgos` con nivel `alto`, `medio` o `info` y una `calificacion` de la A a la F calculada
con reglas fijas (−25 por hallazgo alto, −10 por medio; los informativos no restan).

En DNSSEC el informe distingue **firmado** (hay DNSKEY/DS) de **validado** (el resolutor
marcó la bandera `AD`): no se afirma que esté «seguro» cuando solo hay firmas.

## Probar

```bash
./pruebas/prueba_mcp.sh                      # 401 sin token / 200 con token
.venv/bin/python pruebas/prueba_auditoria.py # initialize, tools/list y estado
.venv/bin/python pruebas/prueba_auditorias.py # auditorías reales y rechazo de SSRF
```

Debe dar **401** sin token, **200** con token y `tools/list` debe incluir `estado`.

## Configuración (`.env`, permisos 600)

| Clave | Para qué |
|---|---|
| `MCP_INTERNO_PUERTO` | Puerto del servidor MCP (127.0.0.1) |
| `MCP_PROXY_PUERTO` | Puerto del proxy con token (0.0.0.0) |
| `MCP_TOKEN` | Token que deben enviar los clientes |
| `MCP_TOKEN_NODIT` | Token exclusivo de Nodit; se revoca quitando su línea y reiniciando |
| `MCP_DOMINIO` | `auditoria.hlquantlabs.trade` |
| `X402_PRECIO_USD` | Precio por llamada, para el alta en Nodit |
| `X402_RED` | `base` |
| `NAVEGADOR_URL` | Endpoint del MCP navegador para la captura |
| `NAVEGADOR_TOKEN` | Token para llamar al MCP navegador |

La plantilla está en `.env.example`:

```bash
cp .env.example .env && chmod 600 .env
openssl rand -hex 32        # valor para MCP_TOKEN
```

**Ningún valor del `.env` se imprime**: `proxy.py` los enmascara todos antes de registrar.

## Nginx y DNS

1. Crear el registro DNS `auditoria.hlquantlabs.trade` en Cloudflare.
2. Copiar `nginx/auditoria.hlquantlabs.trade.conf` a `/etc/nginx/sites-available/`.
3. Enlazarlo en `sites-enabled/`, probar con `sudo nginx -t` y recargar.
4. Emitir el certificado:

```bash
sudo certbot --nginx -d auditoria.hlquantlabs.trade --redirect
```

## Fases

1. **Fase 1:** esqueleto, token, proxy, pruebas y unidad de systemd.
2. **Fase 2 (completa):** `auditar_dominio`, `auditar_correo`, `auditar_web` y `captura`.
3. **Fase 3 (actual):** publicación en MCPize, x402scan y directorios.

La herramienta `captura` llama al MCP navegador con `NAVEGADOR_URL` y
`NAVEGADOR_TOKEN`, usando `browser_navigate` y `browser_take_screenshot`. El token es
**exclusivo de auditoría** (`MCP_TOKEN_AUDITORIA` en el navegador); no se comparte el
token general y se puede revocar por separado.

## Publicación

- `LISTADO.md` reúne los metadatos para Glama, MCP.so, MCP Market y MCPize: nombre,
  descripciones en español e inglés, categoría, etiquetas, herramientas y límites.
- `logo.png` (512×512) y `logo.svg` son el icono del listado.
- El `.env` queda fuera del repositorio por `.gitignore`; el repositorio no lleva
  claves ni datos personales.

## Avisos

- `utils_logging.py` escribe **sin `\n`**: todo va en una línea partida por `\r`. Para
  leer los registros hay que normalizar.
- Cada servicio hermano tiene su propio repositorio y su propio entorno.
- No se comparte código entre `navegador/`, `auditoria/` y `datos-pe/`; se copian las
  piezas comunes a propósito para mantenerlos independientes.
