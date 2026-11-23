import os
import random
import sqlite3
from datetime import datetime
from werkzeug.security import check_password_hash, generate_password_hash

from flask import Flask, flash, redirect, render_template, request, session, url_for
from supabase import Client, create_client


app = Flask(__name__)
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


@app.get("/")
def inicio():
    if not session.get("user_id"):
        return redirect(url_for("login_page"))
    orders = get_orders()
    today_prefix = datetime.utcnow().date().isoformat()
    today_orders = [
        order for order in orders
        if str(order.get("created_at", "")).startswith(today_prefix)
    ]
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
    return render_template(
        "index.html",
        platforms=PLATFORMS,
        connected=connected,
        orders=orders,
        metrics=metrics,
        today=datetime.utcnow().strftime("%A, %d de %B"),
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
    update_order(order_id, request.form["status"])
    return redirect(url_for("inicio"))


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
    return redirect(url_for("inicio") + "#pedidos")


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
