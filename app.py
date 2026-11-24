import csv
import io
import os
import random
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from werkzeug.security import check_password_hash, generate_password_hash

import qrcode
import qrcode.image.svg
from flask import Flask, Response, flash, redirect, render_template, request, session, url_for
from supabase import Client, create_client
from werkzeug.middleware.proxy_fix import ProxyFix


app = Flask(__name__)
# Render pone un proxy delante: así Flask conoce el https y el dominio reales.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = os.getenv("SESSION_SECRET", "desarrollo-local-cambiar")

supabase: Client | None = None
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_ANON_KEY")
if supabase_url and supabase_key:
    supabase = create_client(supabase_url, supabase_key)


def get_supabase_for_session():
    if not supabase or not session.get("supabase_access_token"):
        return None
    client = create_client(supabase_url, supabase_key)
    client.auth.set_session(
        session["supabase_access_token"],
        session.get("supabase_refresh_token", ""),
    )
    return client


def get_db():
    connection = sqlite3.connect("pedidos.db")
    connection.row_factory = sqlite3.Row
    return connection


def ensure_sqlite():
    with get_db() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                customer TEXT NOT NULL,
                total REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'nuevo',
                created_at TEXT NOT NULL,
                user_id TEXT
            )"""
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(orders)").fetchall()
        }
        if "user_id" not in columns:
            connection.execute("ALTER TABLE orders ADD COLUMN user_id TEXT")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS restaurants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                address TEXT,
                created_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS connections (
                user_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, platform)
            )"""
        )
        connection.commit()


ensure_sqlite()


@app.get("/login")
def login_page():
    return render_template("auth.html", mode="login")


@app.get("/registro")
def register_page():
    return render_template("auth.html", mode="register")


@app.post("/login")
def login():
    email = request.form["email"].strip().lower()
    password = request.form["password"]

    if supabase:
        try:
            auth = supabase.auth.sign_in_with_password({
                "email": email,
                "password": password,
            })
            if auth.user and auth.session:
                session["user_id"] = auth.user.id
                session["email"] = email
                session["supabase_access_token"] = auth.session.access_token
                session["supabase_refresh_token"] = auth.session.refresh_token
                return redirect(url_for("inicio"))
        except Exception:
            pass

    with get_db() as connection:
        user = connection.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        flash("Correo o contraseña incorrectos.")
        return redirect(url_for("login_page"))
    session["user_id"] = str(user["id"])
    session["email"] = user["email"]
    return redirect(url_for("inicio"))


SIGNUP_ERRORS = {
    "over_email_send_rate_limit": "Supabase limitó los correos de confirmación (demasiados intentos). Espera un rato o desactiva 'Confirm email' en Supabase.",
    "over_request_rate_limit": "Demasiados intentos seguidos. Espera unos minutos e inténtalo de nuevo.",
    "email_address_invalid": "Supabase no acepta ese correo. Prueba con otro correo real.",
    "weak_password": "La contraseña es demasiado débil. Usa letras, números y más de 8 caracteres.",
    "signup_disabled": "El registro de cuentas está desactivado en Supabase.",
    "user_already_exists": "Ese correo ya está registrado. Inicia sesión.",
    "email_exists": "Ese correo ya está registrado. Inicia sesión.",
}


def describe_signup_error(error):
    code = getattr(error, "code", None)
    if code in SIGNUP_ERRORS:
        return SIGNUP_ERRORS[code]
    detail = getattr(error, "message", None) or str(error) or type(error).__name__
    return f"No se pudo crear la cuenta: {detail}"


@app.post("/registro")
def register():
    email = request.form["email"].strip().lower()
    password = request.form["password"]
    if len(password) < 8:
        flash("La contraseña debe tener al menos 8 caracteres.")
        return redirect(url_for("register_page"))

    if supabase:
        try:
            auth = supabase.auth.sign_up({
                "email": email,
                "password": password,
                "options": {
                    "email_redirect_to": url_for("correo_confirmado", _external=True)
                },
            })
            if auth.user:
                if auth.session:
                    session["user_id"] = auth.user.id
                    session["email"] = email
                    session["supabase_access_token"] = auth.session.access_token
                    session["supabase_refresh_token"] = auth.session.refresh_token
                    return redirect(url_for("inicio"))
                flash("Cuenta creada. Revisa tu correo para confirmar la cuenta.")
                return redirect(url_for("login_page"))
        except Exception as error:
            app.logger.error("Supabase sign_up falló: %r", error)
            flash(describe_signup_error(error))
            return redirect(url_for("register_page"))

    try:
        with get_db() as connection:
            cursor = connection.execute(
                "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                (email, generate_password_hash(password), datetime.utcnow().isoformat()),
            )
            user_id = cursor.lastrowid
            connection.commit()
    except sqlite3.IntegrityError:
        flash("Ese correo ya está registrado.")
        return redirect(url_for("register_page"))
    session["user_id"] = str(user_id)
    session["email"] = email
    return redirect(url_for("inicio"))


@app.get("/confirmado")
def correo_confirmado():
    flash("Correo confirmado. Ya puedes iniciar sesión.")
    return redirect(url_for("login_page"))


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


def get_orders():
    user_id = session.get("user_id")
    if not user_id:
        return []

    authenticated_supabase = get_supabase_for_session()
    if authenticated_supabase:
        try:
            response = authenticated_supabase.table("orders").select("*").order("created_at", desc=True).execute()
            return response.data
        except Exception:
            pass

    with get_db() as connection:
        rows = connection.execute(
            "SELECT id, platform, customer, total, status, created_at FROM orders WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def add_order(platform, customer, total):
    user_id = session.get("user_id")
    if not user_id:
        return

    authenticated_supabase = get_supabase_for_session()
    if authenticated_supabase:
        try:
            authenticated_supabase.table("orders").insert({
                "platform": platform,
                "customer": customer,
                "total": float(total),
                "status": "nuevo",
                "user_id": user_id,
            }).execute()
            return
        except Exception:
            pass

    with get_db() as connection:
        connection.execute(
            "INSERT INTO orders (platform, customer, total, status, created_at, user_id) VALUES (?, ?, ?, 'nuevo', ?, ?)",
            (platform, customer, float(total), datetime.utcnow().isoformat(), user_id),
        )
        connection.commit()


def update_order(order_id, status):
    authenticated_supabase = get_supabase_for_session()
    if authenticated_supabase:
        try:
            authenticated_supabase.table("orders").update({
                "status": status
            }).eq("id", order_id).execute()
            return
        except Exception:
            pass

    user_id = session.get("user_id")
    if not user_id:
        return
    with get_db() as connection:
        connection.execute(
            "UPDATE orders SET status = ? WHERE id = ? AND user_id = ?",
            (status, order_id, user_id),
        )
        connection.commit()


def get_restaurants():
    user_id = session["user_id"]
    client = get_supabase_for_session()
    if client:
        try:
            response = (
                client.table("restaurants")
                .select("id, name, address")
                .order("id", desc=True)
                .execute()
            )
            return response.data
        except Exception:
            pass
    with get_db() as connection:
        return [
            dict(row) for row in connection.execute(
                "SELECT id, name, address FROM restaurants WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            ).fetchall()
        ]


def add_restaurant(name, address):
    user_id = session["user_id"]
    client = get_supabase_for_session()
    if client:
        try:
            client.table("restaurants").insert({
                "user_id": user_id,
                "name": name,
                "address": address,
            }).execute()
            return
        except Exception:
            pass
    with get_db() as connection:
        connection.execute(
            "INSERT INTO restaurants (user_id, name, address, created_at) VALUES (?, ?, ?, ?)",
            (user_id, name, address, datetime.utcnow().isoformat()),
        )
        connection.commit()


def get_alerts():
    user_id = session["user_id"]
    client = get_supabase_for_session()
    if client:
        try:
            response = (
                client.table("alerts")
                .select("id, title, message, read, created_at")
                .order("id", desc=True)
                .execute()
            )
            return response.data
        except Exception:
            pass
    with get_db() as connection:
        return [
            dict(row) for row in connection.execute(
                "SELECT id, title, message, read, created_at FROM alerts WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            ).fetchall()
        ]


def add_alert(title, message):
    user_id = session["user_id"]
    client = get_supabase_for_session()
    if client:
        try:
            client.table("alerts").insert({
                "user_id": user_id,
                "title": title,
                "message": message,
            }).execute()
            return
        except Exception:
            pass
    with get_db() as connection:
        connection.execute(
            "INSERT INTO alerts (user_id, title, message, created_at) VALUES (?, ?, ?, ?)",
            (user_id, title, message, datetime.utcnow().isoformat()),
        )
        connection.commit()


def mark_alert_read(alert_id):
    user_id = session["user_id"]
    client = get_supabase_for_session()
    if client:
        try:
            client.table("alerts").update({"read": True}).eq("id", alert_id).execute()
            return
        except Exception:
            pass
    with get_db() as connection:
        connection.execute(
            "UPDATE alerts SET read = 1 WHERE id = ? AND user_id = ?",
            (alert_id, user_id),
        )
        connection.commit()


QUITO_UTC_OFFSET = timedelta(hours=-5)
DAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
             "septiembre", "octubre", "noviembre", "diciembre"]
DISH_RE = re.compile(r"^(\d+)× (.+)$")
BAR_MAX_PCT = 78  # ancho máximo de la barra; el resto queda para el valor


def _parse_created(value):
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def _ranked(totals, limit, money, icon=None):
    """Convierte {nombre: (valor, pedidos)} en filas ordenadas para las barras."""
    rows = sorted(totals.items(), key=lambda item: item[1][0], reverse=True)[:limit]
    top = max((value for _, (value, _) in rows), default=0) or 1
    result = []
    for name, (value, count) in rows:
        shown = f"${value:,.2f}" if money else f"{int(value)}"
        unit = "pedidos" if count != 1 else "pedido"
        tip = f"{name}: {shown} · {count} {unit}" if money else f"{name}: {shown} unidades"
        result.append({
            "label": f"{icon(name)} {name}" if icon else name, "shown": shown, "tip": tip,
            "pct": round(BAR_MAX_PCT * value / top, 1),
        })
    return result


def build_report(orders):
    platforms, restaurants, dishes = {}, {}, {}
    now = datetime.utcnow() + QUITO_UTC_OFFSET
    slots = [
        (now - timedelta(hours=back)).replace(minute=0, second=0, microsecond=0)
        for back in range(11, -1, -1)
    ]
    hour_counts = {slot: 0 for slot in slots}
    total = 0.0

    for order in orders:
        amount = float(order.get("total") or 0)
        total += amount
        base, _, restaurant = str(order.get("platform", "")).partition(" · ")
        for table, key in ((platforms, base), (restaurants, restaurant)):
            if key:
                value, count = table.get(key, (0.0, 0))
                table[key] = (value + amount, count + 1)
        _, _, items = str(order.get("customer", "")).partition(" — ")
        for part in items.split(", ") if items else []:
            match = DISH_RE.match(part)
            if match:
                name = match.group(2)
                value, count = dishes.get(name, (0, 0))
                dishes[name] = (value + int(match.group(1)), count + 1)
        created = _parse_created(order.get("created_at"))
        if created:
            slot = (created + QUITO_UTC_OFFSET).replace(minute=0, second=0, microsecond=0)
            if slot in hour_counts:
                hour_counts[slot] += 1

    peak = max(hour_counts.values(), default=0)
    hours = [
        {
            "label": f"{slot.hour}h",
            "count": count,
            "pct": round(100 * count / peak, 1) if peak else 0,
        }
        for slot, count in hour_counts.items()
    ]
    return {
        "orders": len(orders),
        "sales": total,
        "avg": total / len(orders) if orders else 0,
        "platforms": _ranked(platforms, 3, money=True),
        "restaurant_totals": restaurants,
        "restaurants": _ranked(restaurants, 5, money=True, icon=restaurant_icon),
        "dishes": _ranked(dishes, 5, money=False, icon=dish_icon),
        "hours": hours,
        "peak": peak,
        "half": peak // 2 if peak >= 4 else None,
    }


STATUS_COLUMNS = [
    ("nuevo", "Nuevo", "✨"), ("preparando", "Preparando", "👨‍🍳"),
    ("listo", "Listo", "✅"), ("entregado", "Entregado", "🛵"),
]
NEXT_STATUS = {"nuevo": "preparando", "preparando": "listo", "listo": "entregado"}
NEXT_LABEL = {"preparando": "Preparar", "listo": "Marcar listo", "entregado": "Entregar"}
VALID_STATUSES = {"nuevo", "preparando", "listo", "entregado", "cancelado", "esperando"}
DELIVERED_VISIBLE = 6


def wants_fetch():
    return request.headers.get("X-Requested-With") == "fetch"


def done(anchor="pedidos"):
    if wants_fetch():
        return "", 204
    return redirect(url_for("inicio") + f"#{anchor}")


def enrich_order(order):
    platform, _, restaurant = str(order.get("platform", "")).partition(" · ")
    who, _, dishes = str(order.get("customer", "")).partition(" — ")
    created = _parse_created(order.get("created_at"))
    status = order.get("status") or "nuevo"
    names = [m.group(2) for m in (DISH_RE.match(p) for p in dishes.split(", ")) if m] if dishes else []
    icons = "".join(dict.fromkeys(dish_icon(name) for name in names))[:6] or "🍽️"
    return {
        "icons": icons,
        "id": order["id"], "who": who, "dishes": dishes, "platform": platform,
        "restaurant": restaurant, "total": float(order.get("total") or 0),
        "status": status, "next": NEXT_STATUS.get(status),
        "next_label": NEXT_LABEL.get(NEXT_STATUS.get(status), ""),
        "created_iso": created.replace(microsecond=0).isoformat() + "Z" if created else "",
    }


def build_board(orders):
    cards = [enrich_order(order) for order in orders]
    columns = []
    for key, label, icon in STATUS_COLUMNS:
        items = [card for card in cards if card["status"] == key]
        extra = max(0, len(items) - DELIVERED_VISIBLE) if key == "entregado" else 0
        columns.append({
            "key": key, "label": label, "icon": icon, "count": len(items),
            "cards": items[:DELIVERED_VISIBLE] if key == "entregado" else items,
            "extra": extra,
        })
    waiting = [card for card in cards if card["status"] == "esperando"]
    cancelled = sum(1 for card in cards if card["status"] == "cancelado")
    return columns, waiting, cancelled


def map_points(restaurant_names, totals):
    points = []
    for restaurant in QUITO_DEMO:
        name = restaurant["name"]
        if name in restaurant_names and name in QUITO_COORDS:
            sales, count = totals.get(name, (0.0, 0))
            lat, lng = QUITO_COORDS[name]
            points.append({
                "icon": restaurant_icon(name),
                "name": name, "address": restaurant["address"], "lat": lat, "lng": lng,
                "orders": count, "sales": round(sales, 2),
            })
    return points


def find_order(order_id):
    return next((o for o in get_orders() if int(o["id"]) == order_id), None)


@app.post("/pedidos/<int:order_id>/agotado")
def plato_agotado(order_id):
    if not session.get("user_id"):
        return redirect(url_for("login_page"))
    order = find_order(order_id)
    if order and order.get("status") == "nuevo":
        update_order(order_id, "esperando")
        who, _, dishes = str(order.get("customer", "")).partition(" — ")
        first = DISH_RE.match(dishes.split(", ")[0]) if dishes else None
        dish = first.group(2) if first else "Un plato"
        add_alert(
            "Plato agotado",
            f"{dish} no está disponible ({who}). Se avisó al cliente para que cancele o acepte un cambio.",
        )
    return done()


@app.post("/pedidos/<int:order_id>/respuesta/<accion>")
def respuesta_cliente(order_id, accion):
    if not session.get("user_id"):
        return redirect(url_for("login_page"))
    order = find_order(order_id)
    if order and order.get("status") == "esperando" and accion in ("acepto", "cancelo"):
        who = str(order.get("customer", "")).partition(" — ")[0]
        if accion == "acepto":
            update_order(order_id, "preparando")
            add_alert("El cliente aceptó el cambio", f"{who}: el pedido sigue en preparación (evento order.fulfillment_issues.resolved).")
        else:
            update_order(order_id, "cancelado")
            add_alert("El cliente canceló el pedido", f"{who}: el pedido fue cancelado por el cliente.")
    return done()


@app.get("/exportar.csv")
def exportar_csv():
    if not session.get("user_id"):
        return redirect(url_for("login_page"))
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "fecha_quito", "plataforma", "restaurante", "cliente", "detalle", "total_usd", "estado"])
    for order in get_orders():
        card = enrich_order(order)
        created = _parse_created(order.get("created_at"))
        local = (created + QUITO_UTC_OFFSET).strftime("%Y-%m-%d %H:%M") if created else ""
        writer.writerow([card["id"], local, card["platform"], card["restaurant"], card["who"],
                         card["dishes"], f'{card["total"]:.2f}', card["status"]])
    return Response(
        "﻿" + buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=pedidos-smart-order.csv"},
    )


def public_url():
    return (os.getenv("PUBLIC_URL") or request.url_root).rstrip("/")


@app.get("/qr.svg")
def qr_code():
    image = qrcode.make(
        public_url() + "/", image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2,
    )
    buffer = io.BytesIO()
    image.save(buffer)
    return Response(
        buffer.getvalue(), mimetype="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/sw.js")
def service_worker():
    response = app.send_static_file("sw.js")
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/manifest.webmanifest")
def manifest():
    response = app.send_static_file("manifest.webmanifest")
    response.mimetype = "application/manifest+json"
    return response


@app.get("/")
def inicio():
    if not session.get("user_id"):
        return redirect(url_for("login_page"))
    orders = get_orders()
    now_quito = datetime.utcnow() + QUITO_UTC_OFFSET
    today_orders = []
    for order in orders:
        created = _parse_created(order.get("created_at"))
        if created and (created + QUITO_UTC_OFFSET).date() == now_quito.date():
            today_orders.append(order)
    sales = sum(float(order.get("total", 0) or 0) for order in today_orders)
    active = sum(
        1 for order in today_orders
        if order.get("status") not in ("entregado", "cancelado")
    )
    connected = get_connections()
    metrics = {
        "today": len(today_orders),
        "active": active,
        "sales": sales,
        "connections": len(connected),
    }
    restaurants = get_restaurants()
    alerts = get_alerts()
    report = build_report(orders)
    columns, waiting, cancelled = build_board(orders)
    return render_template(
        "index.html",
        columns=columns,
        public_url=public_url(),
        waiting=waiting,
        cancelled=cancelled,
        map_points=map_points({r["name"] for r in restaurants}, report["restaurant_totals"]),
        platforms=PLATFORMS,
        connected=connected,
        report=report,
        unread=sum(1 for alert in alerts if not alert.get("read")),
        orders=orders,
        metrics=metrics,
        today=f"{DAYS_ES[now_quito.weekday()]}, {now_quito.day} de {MONTHS_ES[now_quito.month - 1]}",
        restaurants=restaurants,
        alerts=alerts,
    )


@app.post("/pedidos")
def crear_pedido():
    add_order(
        request.form["platform"].strip(),
        request.form["customer"].strip(),
        request.form["total"],
    )
    return redirect(url_for("inicio"))


@app.post("/pedidos/<int:order_id>/estado")
def actualizar_estado(order_id):
    status = request.form["status"]
    if status in VALID_STATUSES:
        update_order(order_id, status)
    return done()


@app.get("/health")
def estado():
    return {"estado": "ok"}


# ---------------------------------------------------------------------------
# Integraciones con plataformas de delivery (MODO DEMO).
# Los formatos de pedido son versiones simplificadas inspiradas en la
# documentación de cada plataforma. Para producción hay que pedir acceso a sus
# APIs de partners y ajustar estos normalizadores al formato real.
# ---------------------------------------------------------------------------

def _label(code, name, items):
    text = f'#{code} · {name or "Cliente"}'
    if items:
        text += " — " + ", ".join(f"{qty}× {dish}" for dish, qty in items)
    return text


def _parse_uber_eats(payload):
    eater = payload.get("eater", {})
    name = f'{eater.get("first_name", "")} {eater.get("last_name", "")}'.strip()
    cents = payload["payment"]["charges"]["total"]["amount"]
    items = [(i["title"], i["quantity"]) for i in payload.get("cart", {}).get("items", [])]
    code = payload.get("display_id", payload.get("id", "?"))
    return _label(code, name, items), cents / 100, payload.get("store", {}).get("name")


def _parse_rappi(payload):
    customer = payload.get("customer", {})
    name = f'{customer.get("first_name", "")} {customer.get("last_name", "")}'.strip()
    items = [(i["name"], i["units"]) for i in payload.get("order_detail", {}).get("items", [])]
    return (
        _label(payload.get("order_id", "?"), name, items),
        payload["totals"]["total_order"],
        payload.get("store", {}).get("name"),
    )


def _parse_pedidosya(payload):
    name = payload.get("user", {}).get("name", "Cliente")
    items = [(i["product"], i["quantity"]) for i in payload.get("details", [])]
    return (
        _label(payload.get("code", "?"), name, items),
        payload["payment"]["amount"],
        payload.get("restaurant", {}).get("name"),
    )


PLATFORMS = {
    "ubereats": {"label": "Uber Eats", "parse": _parse_uber_eats},
    "rappi": {"label": "Rappi", "parse": _parse_rappi},
    "pedidosya": {"label": "PedidosYa", "parse": _parse_pedidosya},
}


# Catálogo demo de Quito: barrios y calles reales, nombres de negocio ficticios.
QUITO_DEMO = [
    {"name": "Sabor Quiteño", "address": "Reina Victoria y Foch, La Mariscal", "menu": [
        ("Encebollado", 3.50), ("Locro de papas", 3.50), ("Seco de pollo", 4.50),
        ("Colada morada", 1.50), ("Empanadas de viento", 1.50)]},
    {"name": "Hornado del Centro", "address": "García Moreno y Sucre, Centro Histórico", "menu": [
        ("Hornado con mote", 6.00), ("Fritada", 6.50), ("Llapingachos", 4.50),
        ("Tortillas con caucara", 4.00)]},
    {"name": "Cevichería La Carolina", "address": "Av. Amazonas y Naciones Unidas, La Carolina", "menu": [
        ("Ceviche de camarón", 7.00), ("Ceviche mixto", 8.00), ("Arroz marinero", 9.00),
        ("Encebollado mixto", 5.50)]},
    {"name": "Parrilla Cumbayá", "address": "Av. Interoceánica y Pampite, Cumbayá", "menu": [
        ("Parrillada para 2", 22.00), ("Churrasco", 9.50), ("Chorizo con papas", 5.50),
        ("Choclo con queso", 3.00)]},
    {"name": "Cocina de la Abuela", "address": "Av. Eloy Alfaro y de los Pinos, El Batán", "menu": [
        ("Bolón de verde", 2.50), ("Caldo de bolas", 4.50), ("Humitas", 2.00),
        ("Café pasado", 1.25), ("Yaguarlocro", 4.00)]},
    {"name": "Pizzería González Suárez", "address": "Av. González Suárez y 12 de Octubre, Quito", "menu": [
        ("Pizza margarita", 9.00), ("Pizza pepperoni", 11.00), ("Lasaña", 8.50),
        ("Pan de ajo", 3.50)]},
]
# Ubicaciones aproximadas para el mapa (latitud, longitud).
QUITO_COORDS = {
    "Sabor Quiteño": (-0.2020, -78.4905),
    "Hornado del Centro": (-0.2205, -78.5115),
    "Cevichería La Carolina": (-0.1807, -78.4846),
    "Parrilla Cumbayá": (-0.2005, -78.4260),
    "Cocina de la Abuela": (-0.1745, -78.4790),
    "Pizzería González Suárez": (-0.2062, -78.4872),
}
DISH_EMOJI = {
    "Encebollado": "🍲", "Encebollado mixto": "🍲", "Locro de papas": "🥣", "Yaguarlocro": "🥣",
    "Seco de pollo": "🍗", "Colada morada": "🥤", "Empanadas de viento": "🥟",
    "Hornado con mote": "🍖", "Fritada": "🥓", "Llapingachos": "🥔", "Tortillas con caucara": "🫓",
    "Ceviche de camarón": "🦐", "Ceviche mixto": "🦐", "Arroz marinero": "🍤",
    "Parrillada para 2": "🥩", "Churrasco": "🥩", "Chorizo con papas": "🌭", "Choclo con queso": "🌽",
    "Bolón de verde": "🍌", "Caldo de bolas": "🍲", "Humitas": "🌽", "Café pasado": "☕",
    "Pizza margarita": "🍕", "Pizza pepperoni": "🍕", "Lasaña": "🍝", "Pan de ajo": "🥖",
}
RESTAURANT_EMOJI = {
    "Sabor Quiteño": "🍲", "Hornado del Centro": "🍖", "Cevichería La Carolina": "🦐",
    "Parrilla Cumbayá": "🥩", "Cocina de la Abuela": "🥘", "Pizzería González Suárez": "🍕",
}


def dish_icon(name):
    return DISH_EMOJI.get(name, "🍽️")


def restaurant_icon(name):
    return RESTAURANT_EMOJI.get(name, "🍴")


@app.context_processor
def inject_icons():
    return {"rest_icon": restaurant_icon}


QUITO_CUSTOMERS = [
    ("Andrés", "Játiva"), ("María Fernanda", "Cevallos"), ("Santiago", "Proaño"),
    ("Daniela", "Chiriboga"), ("Esteban", "Villacís"), ("Paola", "Andrade"),
    ("Juan Carlos", "Narváez"), ("Gabriela", "Endara"), ("Mateo", "Guamán"),
    ("Valeria", "Tipán"),
]
DELIVERY_FEE = 1.50


def pick_demo_order():
    mine = {r["name"] for r in get_restaurants()}
    pool = [r for r in QUITO_DEMO if r["name"] in mine] or QUITO_DEMO
    restaurant = random.choice(pool)
    dishes = random.sample(restaurant["menu"], k=random.randint(1, min(3, len(restaurant["menu"]))))
    lines = [(dish, price, random.randint(1, 2)) for dish, price in dishes]
    total = round(sum(price * qty for _, price, qty in lines) + DELIVERY_FEE, 2)
    return restaurant["name"], lines, total


def sample_payload(platform):
    code = f"{random.randint(1000, 9999)}"
    first, last = random.choice(QUITO_CUSTOMERS)
    restaurant, lines, total = pick_demo_order()
    if platform == "ubereats":
        return {
            "id": f"uber-{code}", "display_id": code,
            "store": {"name": restaurant},
            "eater": {"first_name": first, "last_name": last},
            "cart": {"items": [{"title": d, "quantity": q} for d, _, q in lines]},
            "payment": {"charges": {"total": {"amount": round(total * 100), "currency_code": "USD"}}},
        }
    if platform == "rappi":
        return {
            "order_id": code,
            "store": {"name": restaurant},
            "customer": {"first_name": first, "last_name": last},
            "order_detail": {"items": [{"name": d, "units": q} for d, _, q in lines]},
            "totals": {"total_order": total},
        }
    return {
        "code": code,
        "restaurant": {"name": restaurant},
        "user": {"name": f"{first} {last}"},
        "details": [{"product": d, "quantity": q} for d, _, q in lines],
        "payment": {"amount": total},
    }


def get_connections():
    user_id = session["user_id"]
    client = get_supabase_for_session()
    if client:
        try:
            response = client.table("connections").select("platform").execute()
            return {row["platform"] for row in response.data}
        except Exception:
            pass
    with get_db() as connection:
        rows = connection.execute(
            "SELECT platform FROM connections WHERE user_id = ?", (user_id,)
        ).fetchall()
        return {row["platform"] for row in rows}


def set_connection(platform, connected):
    user_id = session["user_id"]
    client = get_supabase_for_session()
    if client:
        try:
            if connected:
                client.table("connections").upsert(
                    {"user_id": user_id, "platform": platform},
                    on_conflict="user_id,platform",
                ).execute()
            else:
                client.table("connections").delete().eq("platform", platform).execute()
            return
        except Exception:
            pass
    with get_db() as connection:
        if connected:
            connection.execute(
                "INSERT OR IGNORE INTO connections (user_id, platform, created_at) VALUES (?, ?, ?)",
                (user_id, platform, datetime.utcnow().isoformat()),
            )
        else:
            connection.execute(
                "DELETE FROM connections WHERE user_id = ? AND platform = ?",
                (user_id, platform),
            )
        connection.commit()


def ingest_order(platform, payload):
    """Convierte un pedido de una plataforma a nuestro formato y lo guarda."""
    info = PLATFORMS[platform]
    customer, total, restaurant = info["parse"](payload)
    source = f'{info["label"]} · {restaurant}' if restaurant else info["label"]
    add_order(source, customer, total)
    add_alert(f'Nuevo pedido de {info["label"]}', f"{customer} · ${float(total):.2f}")


@app.post("/conexiones/<platform>/<action>")
def cambiar_conexion(platform, action):
    if not session.get("user_id"):
        return redirect(url_for("login_page"))
    if platform in PLATFORMS and action in ("conectar", "desconectar"):
        set_connection(platform, action == "conectar")
    return redirect(url_for("inicio") + "#conexiones")


@app.post("/demo/pedido-entrante/<platform>")
def pedido_entrante_demo(platform):
    if not session.get("user_id"):
        return redirect(url_for("login_page"))
    if platform in PLATFORMS and platform in get_connections():
        ingest_order(platform, sample_payload(platform))
    return done()


# Pedidos por hora del día en Quito: picos en el almuerzo y la cena.
HOURLY_WEIGHT = {8: 1, 9: 1, 10: 2, 11: 3, 12: 6, 13: 7, 14: 4, 15: 1, 16: 1,
                 17: 2, 18: 4, 19: 7, 20: 6, 21: 3, 22: 1}


def demo_history_rows():
    now_utc = datetime.utcnow()
    rows = []
    for back in range(11, -1, -1):
        slot_utc = (now_utc - timedelta(hours=back)).replace(minute=0, second=0, microsecond=0)
        clock_hour = (slot_utc + QUITO_UTC_OFFSET).hour
        is_current = back == 0
        for _ in range(HOURLY_WEIGHT.get(clock_hour, 0)):
            max_minute = now_utc.minute if is_current else 59
            created = slot_utc + timedelta(minutes=random.randint(0, max_minute), seconds=random.randint(0, 59))
            restaurant = random.choice(QUITO_DEMO)
            dishes = random.sample(restaurant["menu"], k=random.randint(1, min(3, len(restaurant["menu"]))))
            lines = [(dish, price, random.randint(1, 2)) for dish, price in dishes]
            total = round(sum(price * qty for _, price, qty in lines) + DELIVERY_FEE, 2)
            first, last = random.choice(QUITO_CUSTOMERS)
            label = PLATFORMS[random.choice(list(PLATFORMS))]["label"]
            recent = (now_utc - created) < timedelta(hours=1)
            rows.append({
                "platform": f'{label} · {restaurant["name"]}',
                "customer": _label(random.randint(1000, 9999), f"{first} {last}",
                                   [(dish, qty) for dish, _, qty in lines]),
                "total": total,
                "status": random.choice(["nuevo", "preparando", "listo"]) if recent else "entregado",
                "created_at": created.isoformat(),
            })
    return rows


def add_orders_bulk(rows):
    user_id = session["user_id"]
    client = get_supabase_for_session()
    if client:
        try:
            client.table("orders").insert([{**row, "user_id": user_id} for row in rows]).execute()
            return
        except Exception:
            pass
    with get_db() as connection:
        connection.executemany(
            "INSERT INTO orders (platform, customer, total, status, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?)",
            [(r["platform"], r["customer"], r["total"], r["status"], r["created_at"], user_id) for r in rows],
        )
        connection.commit()


@app.post("/demo/historial")
def historial_demo():
    if not session.get("user_id"):
        return redirect(url_for("login_page"))
    rows = demo_history_rows()
    if rows:
        add_orders_bulk(rows)
        add_alert("Historial de ejemplo cargado", f"Se agregaron {len(rows)} pedidos de las últimas 12 horas.")
    return redirect(url_for("inicio") + "#reportes")


@app.post("/demo/hora-pico")
def hora_pico_demo():
    if not session.get("user_id"):
        return redirect(url_for("login_page"))
    connected = sorted(get_connections())
    for _ in range(6 if connected else 0):
        platform = random.choice(connected)
        ingest_order(platform, sample_payload(platform))
    return redirect(url_for("inicio") + "#pedidos")


@app.post("/demo/quito")
def cargar_quito_demo():
    if not session.get("user_id"):
        return redirect(url_for("login_page"))
    existing = {r["name"] for r in get_restaurants()}
    added = 0
    for restaurant in QUITO_DEMO:
        if restaurant["name"] not in existing:
            add_restaurant(restaurant["name"], restaurant["address"])
            added += 1
    if added:
        add_alert("Restaurantes de Quito cargados", f"Se agregaron {added} restaurantes de demostración.")
    return redirect(url_for("inicio") + "#restaurantes")


@app.post("/webhooks/<platform>")
def webhook(platform):
    # En modo demo exige sesión. En producción este endpoint lo llamaría la
    # plataforma y habría que identificar al restaurante (token/store id) y
    # guardar con una clave de servicio de Supabase.
    if platform not in PLATFORMS:
        return {"error": "plataforma desconocida"}, 404
    if not session.get("user_id"):
        return {"error": "modo demo: requiere sesión"}, 401
    if platform not in get_connections():
        return {"error": "plataforma no conectada"}, 409
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {"error": "JSON inválido"}, 400
    try:
        ingest_order(platform, payload)
    except (KeyError, TypeError, ValueError):
        return {"error": "formato de pedido inválido"}, 422
    return {"estado": "recibido"}, 201


@app.post("/restaurantes")
def crear_restaurante():
    if not session.get("user_id"):
        return redirect(url_for("login_page"))
    name = request.form["name"].strip()
    address = request.form.get("address", "").strip()
    if name:
        add_restaurant(name, address)
    return redirect(url_for("inicio"))


@app.post("/alertas/<int:alert_id>/leer")
def leer_alerta(alert_id):
    if not session.get("user_id"):
        return redirect(url_for("login_page"))
    mark_alert_read(alert_id)
    return redirect(url_for("inicio"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
