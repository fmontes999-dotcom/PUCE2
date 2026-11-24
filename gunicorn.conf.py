# Gunicorn lee este archivo solo (está en el directorio de trabajo).
# - timeout: Supabase puede tardar varios segundos en algunas operaciones del demo.
# - threads: el panel consulta cada pocos segundos; con un solo hilo las peticiones se encolan.
workers = 1
threads = 4
timeout = 120
