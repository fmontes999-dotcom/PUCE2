import os

from flask import Flask, render_template


app = Flask(__name__)


@app.get("/")
def inicio():
    return render_template("index.html")


@app.get("/health")
def estado():
    return {"estado": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
