import os
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
            flash("No se pudo crear la cuenta.")
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
            "SELECT id, platform, customer, total, status, created_at FROM orders ORDER BY id DESC"
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

    with get_db() as connection:
        connection.execute(
            "UPDATE orders SET status = ? WHERE id = ?",
            (status, order_id),
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
    metrics = {
        "today": len(today_orders),
        "active": active,
        "sales": sales,
        "connections": 3,
    }
    return render_template(
        "index.html",
        orders=orders,
        metrics=metrics,
        today=datetime.utcnow().strftime("%A, %d de %B"),
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
