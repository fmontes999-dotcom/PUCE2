# Smart Order

Panel unificado de pedidos de delivery para restaurantes de Quito. Reúne en un solo tablero los pedidos de Rappi, PedidosYa y Uber Eats, con reportes en vivo, mapa de repartidores y sugerencias para decidir qué preparar.

> **Prototipo académico.** Las plataformas de delivery están **simuladas**: Rappi, PedidosYa y Uber Eats exigen aprobación comercial para dar acceso a sus APIs de partners. Los restaurantes, clientes y precios de Quito son datos de demostración con nombres ficticios.

**En línea:** https://puce2.onrender.com (el plan gratuito de Render se duerme; la primera visita tarda cerca de un minuto).

**Manual de uso (PDF):** [`docs/Manual-SmartOrder-IA.pdf`](docs/Manual-SmartOrder-IA.pdf)

## Qué hace

- **Tablero Kanban** de pedidos: Nuevo → Preparando → Listo → En camino → Entregado. Se mueven con un botón o arrastrando.
- **En vivo, sin recargar:** aviso con sonido, tiempo transcurrido por pedido y alerta en rojo a los 15 minutos.
- **Simulación en vivo:** entra un pedido cada 15 segundos y los pedidos avanzan solos.
- **Reportes:** ventas por plataforma, pedidos por hora, platos más pedidos y ventas por restaurante.
- **Pronóstico de demanda:** un modelo estadístico que aprende de los pedidos de cada usuario y predice las próximas 6 horas de atención (ver más abajo).
- **Sugerencias del asistente:** reglas simples sobre los datos (no es IA generativa).
- **Plato agotado:** el pedido queda "esperando al cliente" y el plato se marca agotado en el menú.
- **Menú:** disponibilidad de platos por restaurante.
- **Repartidores en el mapa** de Quito (OpenStreetMap + Leaflet).
- **Factura de ejemplo** por pedido (sin validez tributaria), exportación a **CSV** y a **PDF** (impresión).
- **Modo oscuro**, **instalable en el celular** (PWA) y **código QR** para abrir la app desde el teléfono.
- **Cuentas con aislamiento por usuario**: cada persona solo ve sus propios datos.

## Demo en 1 minuto

1. Crea una cuenta en `/registro`.
2. Pulsa **✨ Preparar demo** (carga restaurantes de Quito, conecta las 3 plataformas y llena el día).
3. Activa **▶ Simulación en vivo** y arrastra un pedido entre columnas.
4. Prueba **Plato agotado** → **Cliente aceptó**.
5. Mira el mapa, cambia al modo oscuro y descarga el CSV.
6. **↺ Reiniciar demo** borra los datos de tu cuenta para empezar de cero.

## Modelo de pronóstico (gratis y escalable)

`forecast_demand()` en [`app.py`](app.py) aprende de tu historial y predice cuántos pedidos esperar en cada una de las próximas horas de atención:

1. **Aprende el patrón de cada hora** del día con un promedio ponderado de los últimos 14 días (los días recientes pesan más). Separa días de entre semana y fines de semana cuando hay datos suficientes.
2. **Se ajusta al día de hoy** comparando las últimas 3 horas reales con lo esperado (limitado entre −30 % y +50 %).
3. **Descarta el día más antiguo si está incompleto** (el historial suele empezar a media jornada).
4. **Se evalúa a sí mismo:** predice los últimos días usando solo lo anterior a cada uno y muestra el error medio junto al de un método ingenuo ("lo mismo que ayer").
5. Con la tasa de unidades por pedido estima cuánto preparar del plato más pedido.

**Gratis:** Python puro, sin claves ni servicios externos. **Escalable:** una pasada O(n) sobre los pedidos y solo mira los últimos días (50 000 pedidos se procesan en menos de 0,1 s); si el volumen crece, el mismo cálculo puede moverse a una tarea nocturna o a una consulta agregada en SQL sin cambiar el modelo.

**Límites honestos:** es un modelo estadístico sencillo, no aprendizaje profundo. Necesita al menos 2 días de historial y, con los datos de demostración (ruido aleatorio sobre un patrón fijo), su ventaja sobre el método ingenuo es modesta. Con pedidos reales mejorará a medida que acumule semanas de datos.

## Tecnología

- Python 3 + Flask, servido con Gunicorn.
- Supabase (Auth + Postgres con RLS). Si Supabase no responde, usa SQLite local como respaldo.
- HTML, CSS y JavaScript sin frameworks. Leaflet para el mapa y `qrcode` para el QR.
- Despliegue en Render (`render.yaml`).

## Ejecutar en local

```bash
python -m venv .venv
.venv\Scripts\activate          # en Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
python app.py                   # http://localhost:5000
```

Sin variables de entorno funciona con SQLite local. Los datos se guardan en `pedidos.db` (ignorado por git).

### Variables de entorno

| Variable | Para qué sirve |
|---|---|
| `SESSION_SECRET` | Clave de las sesiones (Render la genera sola). |
| `SUPABASE_URL` | URL del proyecto de Supabase. |
| `SUPABASE_ANON_KEY` | Clave pública (anon) de Supabase. |
| `PUBLIC_URL` | Opcional: dirección que lleva el código QR (por defecto, la del sitio). |

## Base de datos (Supabase)

1. Crea un proyecto en Supabase.
2. En **SQL Editor** ejecuta todo el contenido de [`supabase_schema.sql`](supabase_schema.sql). Es seguro repetirlo.
3. Para pruebas, apaga **Authentication → Sign In / Providers → Email → Confirm email** (el correo integrado de Supabase tiene un límite muy bajo de envíos por hora).

Tablas: `orders`, `restaurants`, `alerts`, `connections`, `unavailable_dishes`, todas con RLS por `auth.uid()`.

## Estructura

```
app.py                  Rutas, lógica de pedidos, reportes, demo y respaldo SQLite
templates/              index.html (panel), landing.html, auth.html, factura.html
static/                 styles.css, main.js, logos (logo-full.png, logo-icon.png, icon-*.png), sw.js, manifest.webmanifest
supabase_schema.sql     Tablas y políticas de seguridad
render.yaml, Procfile   Despliegue
```

## Limitaciones y siguientes pasos

- Pedir acceso a las APIs de partners de Rappi, PedidosYa y Uber Eats y reemplazar los pedidos simulados. Los webhooks (`/webhooks/<plataforma>`) ya existen, pero hoy exigen sesión y usan formatos simplificados.
- Menús editables, alertas por WhatsApp, facturación electrónica real con el SRI y predicción de demanda con IA.
- Reactivar "Confirm email" con un servidor SMTP propio y usar un plan de hosting que no se duerma.
