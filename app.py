import os

from flask import Flask, redirect, render_template, request, url_for
from supabase import Client, create_client


app = Flask(__name__)

supabase: Client | None = None
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_ANON_KEY")
if supabase_url and supabase_key:
    supabase = create_client(supabase_url, supabase_key)


@app.get("/")
def inicio():
    orders = []
    if supabase:
        response = supabase.table("orders").select("*").order("created_at", desc=True).execute()
        orders = response.data
    return render_template("index.html", orders=orders)


@app.post("/pedidos")
def crear_pedido():
    if not supabase:
        return redirect(url_for("inicio"))

    supabase.table("orders").insert({
        "platform": request.form["platform"].strip(),
        "customer": request.form["customer"].strip(),
        "total": float(request.form["total"]),
        "status": "nuevo",
    }).execute()
    return redirect(url_for("inicio"))


@app.post("/pedidos/<int:order_id>/estado")
def actualizar_estado(order_id):
    if supabase:
        supabase.table("orders").update({
            "status": request.form["status"]
        }).eq("id", order_id).execute()
    return redirect(url_for("inicio"))


@app.get("/health")
def estado():
    return {"estado": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
