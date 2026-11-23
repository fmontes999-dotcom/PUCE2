import os
import sqlite3
from datetime import datetime

from flask import Flask, redirect, render_template, request, url_for
from supabase import Client, create_client


app = Flask(__name__)

supabase: Client | None = None
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_ANON_KEY")
if supabase_url and supabase_key:
    supabase = create_client(supabase_url, supabase_key)


def get_db():
    connection = sqlite3.connect("pedidos.db")
    connection.row_factory = sqlite3.Row
    return connection


def ensure_sqlite():
    with get_db() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                customer TEXT NOT NULL,
                total REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'nuevo',
                created_at TEXT NOT NULL
            )"""
        )
        connection.commit()


ensure_sqlite()


def get_orders():
    if supabase:
        try:
            response = supabase.table("orders").select("*").order("created_at", desc=True).execute()
            return response.data
        except Exception:
            pass

    with get_db() as connection:
        rows = connection.execute(
            "SELECT id, platform, customer, total, status, created_at FROM orders ORDER BY id DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def add_order(platform, customer, total):
    if supabase:
        try:
            supabase.table("orders").insert({
                "platform": platform,
                "customer": customer,
                "total": float(total),
                "status": "nuevo",
            }).execute()
            return
        except Exception:
            pass

    with get_db() as connection:
        connection.execute(
            "INSERT INTO orders (platform, customer, total, status, created_at) VALUES (?, ?, ?, 'nuevo', ?)",
            (platform, customer, float(total), datetime.utcnow().isoformat()),
        )
        connection.commit()


def update_order(order_id, status):
    if supabase:
        try:
            supabase.table("orders").update({
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
    return render_template("index.html", orders=get_orders())


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
