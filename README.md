# Monitor regulatorio de gasolineras (Profeco · CNE · ASEA)

Se ejecuta 4 veces al día (7, 11, 15 y 19 h CDMX) en GitHub Actions: recolecta noticias y comunicados,
los clasifica con Claude (urgente / medio / bajo) y publica el panel web con generador de reportes.

## Puesta en marcha (≈10 min)
1. Crea un repositorio en GitHub y sube todo el contenido de esta carpeta (incluida `.github/`).
2. Settings → Secrets and variables → Actions → New secret:
   - `ANTHROPIC_API_KEY` (obligatorio, desde console.anthropic.com)
   - `ALERT_WEBHOOK` (opcional: URL de webhook de Slack o Discord para avisos de urgentes)
3. Settings → Pages → Source: **GitHub Actions**.
4. Pestaña Actions → monitor → **Run workflow**. Al terminar, tu panel queda en la URL de Pages.

## Ajustes
- Fuentes: `sources.json`. Las páginas `gob.mx/.../prensa` deben revisarse; si alguna cambia de ruta, corrígela.
- Frecuencia: línea `cron` en `.github/workflows/monitor.yml` (hora UTC).
- Modelo: variable `CLAUDE_MODEL` (por defecto claude-haiku-5-5, el más económico).
- Criterios de urgencia: texto `SYSTEM` en `monitor.py`.
- Ejecución local de prueba: `pip install -r requirements.txt && ANTHROPIC_API_KEY=... python monitor.py`

## Botón «Buscar novedades ahora»
Dispara el workflow bajo demanda y espera el resultado (2–4 min).
1. GitHub → Settings → Developer settings → Fine-grained personal access tokens → Generate.
2. Repositorio: solo este. Permiso: **Actions → Read and write**.
3. En el panel abre «⚙ Conexión con GitHub», escribe `usuario/repositorio`, la rama y el token.
Abriendo la dirección del panel con `#buscar` (lo hace el botón de la versión en Claude) la búsqueda arranca sola.
Sin token el botón no funciona; el workflow también se puede lanzar desde la pestaña Actions.
La búsqueda incluye la edición diaria del **DOF** (`from_dof` en `monitor.py`), Google News y las páginas de prensa.

## Alcance temporal
- Solo se conservan noticias del **año en curso** y de los **últimos 7 días** (ajustable con `WINDOW_DAYS` en el workflow).
- Se usa la fecha real de publicación (RSS, metadatos o texto de la página). Si no se puede determinar, la nota se descarta.
- El panel tiene los filtros **Hoy** y **Esta semana**. Lo que supera los 7 días se elimina solo.

## Límites
- Las noticias vienen de buscadores y portales, no del DOF directamente; añade fuentes oficiales en `sources.json`.
- La clasificación es automática: revisa siempre la fuente antes de informar a un cliente.
- El panel es público si el repositorio de Pages lo es; usa un plan o repositorio privado si lo necesitas restringido.
