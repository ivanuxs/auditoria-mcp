# AGENTS.md — Reglas del proyecto `mcp/auditoria`

Servidor **MCP** de auditoría web y de correo: dominio, DNS, TLS, correo y web,
con resultados deterministas para agentes de IA.
Proyecto **independiente**: no comparte código, entorno ni configuración con
`../navegador/` ni con `../../../Publicaciones/`. Vive bajo `mcp/` porque habrá
más servidores MCP aquí (uno por carpeta y por repositorio).

---

## 0. Idioma

**Háblale siempre al usuario en español** (neutro peruano, con tuteo). También los
comentarios, los docstrings y los mensajes del código.

## 1. Plan antes de tocar

Ningún cambio se hace sin que el usuario diga **«procede»**. Primero se presenta el plan
con los pasos y una recomendación; se espera. Responder preguntas **no** autoriza a
implementar.

## 2. Claves y secretos

- Las claves viven **solo** en el `.env` (permisos `600`). Nunca en el código ni en git.
- **Todo valor del `.env` se enmascara** en los registros y en la consola: `MCP_TOKEN`,
  `MCP_TOKEN_NODIT` y `NAVEGADOR_TOKEN`.
- También se enmascaran las cabeceras sensibles: `Authorization`, `x-api-key`, `cookie`.
- No se imprime nunca el contenido del `.env`, ni completo ni por partes.

## 3. Registros

- Se usa `utils_logging.py` (copia autónoma de la de `navegador/`), no `print` sueltos.
- **Ojo:** ese módulo escribe **sin `\n`**, todo en una línea partida por `\r` y con una
  marca `[funcion:linea]` al final. Para leerlo hay que normalizar.
- Los registros van en `logs/`.

## 4. El servidor no queda abierto

- El MCP escucha **solo** en `127.0.0.1:8940`.
- Lo único expuesto es el proxy en `8941`, y **exige token**: sin `Authorization: Bearer`
  correcto devuelve `401` sin ejecutar nada.
- Cualquier herramienta nueva hereda esa protección.

## 5. Reinicio sin `sudo`

La unidad corre como `oficina-2` y tiene `Restart=on-failure` con `RestartSec=5`. Para
reiniciar el servicio sin contraseña se mata el proxy; `arrancar.sh` termina con código
distinto de cero, su `trap` cierra el MCP y systemd lo levanta otra vez:

```bash
pkill -TERM -f 'auditoria/.venv/bin/python proxy.py'
```

- **No** se mata el servidor MCP a secas: el proxy quedaría vivo y el puerto interno ocupado.
- **No** se usa SIGKILL sobre `arrancar.sh`: no correría su `trap` y el MCP quedaría
  huérfano ocupando el 8940.
- Tras unos segundos, comprobar `systemctl is-active mcp-auditoria` y que `8940` y `8941`
  vuelvan a escuchar; si no, mirar `logs/mcp_salida.txt`.
- `systemctl stop` sigue necesitando `sudo`; esto solo sirve para reiniciar.

## 6. Alcance

- No se toca `../navegador/` ni `../../../Publicaciones/`: son proyectos hermanos.
- Cada servicio hermano tiene su **propio repositorio**, `.env`, `.venv`, logs y token.
- No se añaden herramientas «por si acaso». Cada una se justifica y se prueba.
- Las pruebas se ejecutan cuando el usuario lo dice.

## 7. Datos y cumplimiento

- Solo se consultan fuentes públicas o con permiso expreso.
- Se respetan los términos de uso, `robots.txt` y los límites de cada fuente.
- No se almacenan datos personales; los resultados se cachean solo el tiempo necesario.
- Toda salida debe indicar la fuente y la fecha de la consulta.

## 8. Cuando pase a producción

- Los pilotos corren primero en `oficina-2`; después se trasladan a servidores dedicados.
- La puerta pública será `auditoria.hlquantlabs.trade`, con nginx delante y Cloudflare encima.
- El cobro irá por Nodit Agent PayGate o Cloudflare Monetization Gateway; nunca ambos a la vez.
