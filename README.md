# Auditoría MCP

Domain, email and web audits for AI agents in a single tool call: DNS, RDAP, TLS,
SPF, DMARC, DKIM, MTA-STS, BIMI, security headers and cookies — with findings graded
high, medium or informational and an A–F score.

**Español:** auditorías de dominio, correo y web en una llamada, con hallazgos
clasificados y nota de la A a la F. Las reglas son fijas, así que el resultado es
reproducible y sirve para comparar dominios o seguirlos en el tiempo.

## Connect

| | |
|---|---|
| Endpoint | `https://auditoria.hlquantlabs.trade/mcp` |
| Transport | Streamable HTTP (SSE responses) |
| Auth | `Authorization: Bearer <token>` — without it, `401` |

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

## Tools

| Tool | Parameters | Returns |
|---|---|---|
| `estado` | — | Service version and status |
| `auditar_dominio` | `dominio`* | DNS, RDAP, TLS, findings, grade |
| `auditar_dns` | `dominio`* | CAA, DNSSEC, SOA, CNAME, TTL, findings, grade |
| `auditar_correo` | `dominio`* | MX, SPF, DMARC, DKIM, MTA-STS, BIMI, findings, grade |
| `comparar` | `dominios`* | Per-domain summary and worst-to-best order |
| `auditar_web` | `url`* | Status, redirects, headers, cookies, findings, grade |
| `captura` | `url`*, `completa` | PNG screenshot plus metadata |

`*` required.

## Notes and limits

- Public domains and URLs only. Private and loopback addresses are rejected, as is
  anything pointing at the server's own network.
- Read-only: it inspects public records and never sends mail or changes configuration.
- Domains with only MX and no A/AAAA record are handled correctly.
- DNSSEC reports `firmado` (keys or DS present) and `validado` (resolver set the `AD`
  flag) separately; signatures alone are not claimed to be validated.
- `comparar` accepts 2 to 5 domains and subtracts 25 points per high finding and 10 per
  medium one; informational findings do not lower the grade.
- Nothing is cached between calls; every report is computed live.

## Docs

- [`LISTADO.md`](LISTADO.md) — listing metadata for MCP directories (ES/EN), tools,
  limits and a `curl` check.
- [`LEEME.md`](LEEME.md) — operating notes in Spanish: proxy, ports, systemd, nginx.

## License

MIT. See [LICENSE](LICENSE). The hosted service is sold separately under a token.

## Contact

`soporte@hlquantlabs.trade`
