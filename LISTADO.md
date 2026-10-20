# Ficha de listado — Auditoría MCP

Metadatos para publicar este servidor en Glama, MCP.so, MCP Market y MCPize.
Copia y pega; no hay que reescribir nada.

## Identidad

| Campo | Valor |
|---|---|
| Nombre | Auditoría MCP |
| Slug | `auditoria-mcp` |
| Título | Auditoría MCP — salud de dominio, correo y web |
| Versión | 0.2.0 |
| Categoría | Security & Compliance |
| Etiquetas | `security`, `dns`, `tls`, `email`, `spf`, `dmarc`, `headers`, `audit`, `peru` |
| Icono | `logo.png` (512×512) o `logo.svg` |
| Licencia del código | MIT |
| Licencia del servicio | Uso comercial bajo token |
| Contacto | Ivan Medina Soto — `soporte@hlquantlabs.trade` — Perú |

## Descripción corta (≤160 caracteres)

> Auditorías de dominio, correo y web en una llamada: DNS, TLS, SPF, DMARC, cabeceras y cookies, con hallazgos y nota de la A a la F.

English:

> Domain, email and web audits in one call: DNS, TLS, SPF, DMARC, headers and cookies, with findings and an A–F grade.

## Descripción larga

> Un auditor que responde con hechos, no con adjetivos. Con una sola llamada revisa
> DNS, registro RDAP y certificado TLS de un dominio; con otra, todo lo que decide si
> un correo llega o cae en spam: MX, SPF, DMARC, DKIM, MTA-STS y BIMI. La tercera mira
> una URL concreta: código de estado, cadena de redirecciones, cabeceras de seguridad y
> cookies.
>
> Cada informe trae hallazgos clasificados en alto, medio e informativo, y una nota de
> la A a la F calculada según esos hallazgos. Las reglas son fijas y el resultado es el
> mismo siempre, así que sirve para comparar dominios entre sí o seguir su evolución en
> el tiempo.
>
> Incluye captura de pantalla de una URL, útil para adjuntar evidencia visual al
> informe sin abrir un navegador.

English:

> An auditor that answers with facts, not adjectives. One call checks DNS, the RDAP
> record and the TLS certificate of a domain. Another checks what decides whether mail
> is delivered or lands in spam: MX, SPF, DMARC, DKIM, MTA-STS and BIMI. A third looks
> at a specific URL: status code, redirect chain, security headers and cookies.
>
> Every report returns findings graded high, medium or informational, plus an A–F
> score derived from those findings. Rules are deterministic and results are
> reproducible, so domains can be compared with each other or tracked over time.
>
> It also captures a screenshot of a URL, handy for attaching visual evidence to a
> report without opening a browser.

## Conexión

| Campo | Valor |
|---|---|
| Endpoint | `https://auditoria.hlquantlabs.trade/mcp` |
| Transporte | Streamable HTTP, con respuestas SSE |
| Autenticación | Cabecera `Authorization: Bearer <token>` |
| Sin token | `401`, no se ejecuta nada |

```json
{
  "mcpServers": {
    "auditoria": {
      "type": "http",
      "url": "https://auditoria.hlquantlabs.trade/mcp",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

## Herramientas (5)

| Herramienta | Parámetros | Devuelve |
|---|---|---|
| `estado` | — | Versión y estado del servicio |
| `auditar_dominio` | `dominio`* | DNS, RDAP, TLS, hallazgos y nota |
| `auditar_correo` | `dominio`* | MX, SPF, DMARC, DKIM, MTA-STS, BIMI, hallazgos y nota |
| `auditar_web` | `url`* | Estado, redirecciones, cabeceras, cookies, hallazgos y nota |
| `captura` | `url`*, `completa` | Imagen PNG y metadatos |

`*` obligatorio.

## Ejemplos de uso

- «Audita `midominio.pe` y dime qué le falta para no caer en spam.»
- «Compara la configuración de correo de estos tres dominios y ordena de peor a mejor.»
- «Revisa las cabeceras de seguridad de esta web y qué nota saca.»
- «Captura esta página y adjúntala al informe.»

## Límites conocidos

- Solo acepta dominios y URLs públicas. Rechaza direcciones privadas, locales y
  cualquier intento de alcanzar la red interna del servidor.
- No envía correo ni modifica configuración: solo lee registros públicos.
- `auditar_dominio` y `auditar_correo` toleran dominios sin registro A o AAAA, algo
  habitual en dominios de solo correo.
- Los resultados se calculan en el momento; no hay caché entre llamadas.

## Verificación

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://auditoria.hlquantlabs.trade/mcp   # 401

curl -s -X POST https://auditoria.hlquantlabs.trade/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"prueba","version":"1"}}}'
```
