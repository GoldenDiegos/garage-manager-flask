from flask import Flask, jsonify, request, render_template, redirect, url_for, session
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "database", "database.db")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
PUBLIC_ENDPOINTS = {
    "static",
    "login_page",
    "register_page",
    "logout",
    "create_user",
    "initialize_database",
}

# -------------------------
# DB HELPERS
# -------------------------

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cars (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        brand TEXT NOT NULL,
        model TEXT NOT NULL,
        year INTEGER NOT NULL,
        plate TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS service_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        car_id INTEGER NOT NULL,
        service_type TEXT NOT NULL,
        service_date TEXT NOT NULL,
        mileage INTEGER NOT NULL,
        cost REAL NOT NULL,
        FOREIGN KEY (car_id) REFERENCES cars(id) ON DELETE CASCADE
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS car_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        car_id INTEGER NOT NULL,
        doc_type TEXT NOT NULL,
        folio TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        notes TEXT,
        FOREIGN KEY (car_id) REFERENCES cars(id) ON DELETE CASCADE
    )
    """)

    conn.commit()
    conn.close()


def fetch_car_with_owner(conn, car_id: int):
    return conn.execute("""
        SELECT
            cars.id,
            cars.user_id,
            users.name AS user_name,
            cars.brand,
            cars.model,
            cars.year,
            cars.plate
        FROM cars
        JOIN users ON users.id = cars.user_id
        WHERE cars.id = ?
    """, (car_id,)).fetchone()


def fetch_document(conn, doc_id: int):
    return conn.execute("""
        SELECT id, car_id, doc_type, folio, expires_at, notes
        FROM car_documents
        WHERE id = ?
    """, (doc_id,)).fetchone()


def create_user_in_db(name: str, email: str, password: str):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
            (name, email, generate_password_hash(password)),
        )
        conn.commit()
        user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        return None, "email_exists"

    conn.close()
    return user_id, None


def verify_password(stored_password: str, raw_password: str):
    if stored_password.startswith("scrypt:") or stored_password.startswith("pbkdf2:"):
        return check_password_hash(stored_password, raw_password)
    return stored_password == raw_password


@app.before_request
def enforce_authentication():
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if request.endpoint is None:
        return None
    if request.method == "OPTIONS":
        return None
    if session.get("user_id"):
        return None
    if request.path.startswith("/view") or request.path == "/":
        return redirect(url_for("login_page"))
    return jsonify({"error": "No autenticado"}), 401


@app.context_processor
def inject_user():
    return {
        "is_authenticated": bool(session.get("user_id")),
        "current_user_name": session.get("user_name"),
        "current_user_email": session.get("user_email"),
    }


init_db()


# -------------------------
# VISTAS (TEMPLATES)
# -------------------------

@app.route("/")
def home():
    if not session.get("user_id"):
        return redirect(url_for("login_page"))
    return redirect(url_for("cars_page"))


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "GET":
        if session.get("user_id"):
            return redirect(url_for("cars_page"))
        return render_template("auth/login.html", error=None)

    data = request.get_json(silent=True) if request.is_json else request.form
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not email or not password:
        error = "Faltan campos obligatorios: email, password"
        if request.is_json:
            return jsonify({"error": error}), 400
        return render_template("auth/login.html", error=error), 400

    conn = get_db_connection()
    user = conn.execute(
        "SELECT id, name, email, password FROM users WHERE email = ?",
        (email,),
    ).fetchone()

    if user is None or not verify_password(user["password"], password):
        conn.close()
        error = "Credenciales invalidas"
        if request.is_json:
            return jsonify({"error": error}), 401
        return render_template("auth/login.html", error=error), 401

    # Migra automaticamente passwords antiguas guardadas en texto plano.
    if not (user["password"].startswith("scrypt:") or user["password"].startswith("pbkdf2:")):
        conn.execute(
            "UPDATE users SET password = ? WHERE id = ?",
            (generate_password_hash(password), user["id"]),
        )
        conn.commit()

    conn.close()
    session.clear()
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    session["user_email"] = user["email"]

    if request.is_json:
        return jsonify({"message": "Login correcto"}), 200

    return redirect(url_for("cars_page"))


@app.route("/register", methods=["GET", "POST"])
def register_page():
    if request.method == "GET":
        return render_template("auth/register.html", error=None)

    data = request.get_json(silent=True) if request.is_json else request.form
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not name or not email or not password:
        error = "Faltan campos obligatorios: name, email, password"
        if request.is_json:
            return jsonify({"error": error}), 400
        return render_template("auth/register.html", error=error), 400

    user_id, create_error = create_user_in_db(name, email, password)
    if create_error == "email_exists":
        error = "El email ya esta registrado"
        if request.is_json:
            return jsonify({"error": error}), 409
        return render_template("auth/register.html", error=error), 409

    if request.is_json:
        return jsonify({"message": "Usuario creado", "id": user_id}), 201

    return redirect(url_for("login_page"))


@app.route("/logout", methods=["GET"])
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/init-db")
def initialize_database():
    init_db()
    return "Base de datos inicializada correctamente"


# --- Cars templates ---
@app.route("/view/cars")
def cars_page():
    return render_template("cars/cars.html")


@app.route("/view/cars/create")
def cars_create_page():
    return render_template("cars/create_car.html")


@app.route("/view/cars/<int:car_id>/edit")
def cars_edit_page(car_id):
    conn = get_db_connection()
    car = conn.execute("SELECT * FROM cars WHERE id = ?", (car_id,)).fetchone()
    conn.close()

    if car is None:
        return "Car not found", 404

    return render_template("cars/edit_car.html", car=car)


# --- Users templates ---
@app.route("/view/users")
def users_page():
    return render_template("users/user.html")


@app.route("/view/users/create")
def users_create_page():
    return render_template("users/create_user.html")


# --- Services templates (genéricas) ---
@app.route("/view/services")
def services_page():
    return render_template("services/services.html")


@app.route("/view/services/create")
def services_create_page():
    return render_template("services/create_service.html")


@app.route("/view/services/<int:service_id>/edit")
def services_edit_page(service_id):
    conn = get_db_connection()
    service = conn.execute("SELECT * FROM service_records WHERE id = ?", (service_id,)).fetchone()
    conn.close()

    if service is None:
        return "Service record not found", 404

    return render_template("services/edit_service.html", service=service)


# -------------------------
# ✅ DOCUMENTS (por carro)
# -------------------------

@app.route("/view/cars/<int:car_id>/documents", methods=["GET"])
def view_car_documents(car_id):
    """
    Vista por carro: documentos.
    Template: templates/documents/car_documents.html   ✅
    """
    conn = get_db_connection()

    car = fetch_car_with_owner(conn, car_id)
    if car is None:
        conn.close()
        return "Car not found", 404

    documents = conn.execute("""
        SELECT id, car_id, doc_type, folio, expires_at, notes
        FROM car_documents
        WHERE car_id = ?
        ORDER BY expires_at DESC
    """, (car_id,)).fetchall()

    conn.close()
    return render_template("documents/car_documents.html", car=car, documents=documents)


@app.route("/cars/<int:car_id>/documents", methods=["POST"])
def create_document_by_car(car_id):
    """
    Crear documento para un coche.
    - Template (form-data): redirige a /view/cars/<id>/documents
    - Postman (JSON): responde JSON 201
    """
    data_json = request.get_json(silent=True)

    if data_json:
        doc_type = (data_json.get("doc_type") or "").strip()
        folio = (data_json.get("folio") or "").strip()
        expires_at = (data_json.get("expires_at") or "").strip()
        notes = (data_json.get("notes") or "").strip()
    else:
        doc_type = (request.form.get("doc_type") or "").strip()
        folio = (request.form.get("folio") or "").strip()
        expires_at = (request.form.get("expires_at") or "").strip()
        notes = (request.form.get("notes") or "").strip()

    if not doc_type or not folio or not expires_at:
        if data_json:
            return jsonify({"error": "Faltan campos: doc_type, folio, expires_at"}), 400
        return "Faltan campos del formulario", 400

    conn = get_db_connection()

    car_exists = conn.execute("SELECT id FROM cars WHERE id = ?", (car_id,)).fetchone()
    if car_exists is None:
        conn.close()
        if data_json:
            return jsonify({"error": "Coche no encontrado"}), 404
        return "Car not found", 404

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO car_documents (car_id, doc_type, folio, expires_at, notes)
        VALUES (?, ?, ?, ?, ?)
    """, (car_id, doc_type, folio, expires_at, notes if notes else None))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()

    if data_json:
        return jsonify({"message": "Documento creado", "id": new_id}), 201

    return redirect(url_for("view_car_documents", car_id=car_id))


@app.route("/documents/<int:doc_id>/edit", methods=["GET", "POST"])
def edit_document(doc_id):
    """
    Editar documento:
    - GET: templates/documents/edit_document.html
    - POST: actualiza y regresa a /view/cars/<car_id>/documents
    """
    conn = get_db_connection()
    document = fetch_document(conn, doc_id)

    if document is None:
        conn.close()
        return "Document not found", 404

    car = fetch_car_with_owner(conn, document["car_id"])
    if car is None:
        conn.close()
        return "Car not found", 404

    if request.method == "GET":
        conn.close()
        return render_template("documents/edit_document.html", car=car, document=document)

    # POST
    doc_type = (request.form.get("doc_type") or "").strip()
    folio = (request.form.get("folio") or "").strip()
    expires_at = (request.form.get("expires_at") or "").strip()
    notes = (request.form.get("notes") or "").strip()

    if not doc_type or not folio or not expires_at:
        conn.close()
        return "Faltan campos del formulario", 400

    cursor = conn.cursor()
    cursor.execute("""
        UPDATE car_documents
        SET doc_type = ?, folio = ?, expires_at = ?, notes = ?
        WHERE id = ?
    """, (doc_type, folio, expires_at, notes if notes else None, doc_id))
    conn.commit()
    conn.close()

    return redirect(url_for("view_car_documents", car_id=car["id"]))


@app.route("/documents/<int:doc_id>/delete", methods=["POST"])
def delete_document_template(doc_id):
    """
    Delete desde template (form POST).
    """
    conn = get_db_connection()
    document = fetch_document(conn, doc_id)

    if document is None:
        conn.close()
        return "Document not found", 404

    car_id = document["car_id"]

    cursor = conn.cursor()
    cursor.execute("DELETE FROM car_documents WHERE id = ?", (doc_id,))
    conn.commit()
    conn.close()

    return redirect(url_for("view_car_documents", car_id=car_id))


# -------------------------
# API USERS (CRUD)
# -------------------------

@app.route("/users", methods=["POST"])
def create_user():
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not name or not email or not password:
        return jsonify({"error": "Faltan campos obligatorios: name, email, password"}), 400

    user_id, create_error = create_user_in_db(name, email, password)
    if create_error == "email_exists":
        return jsonify({"error": "El email ya está registrado"}), 409
    return jsonify({"message": "Usuario creado", "id": user_id}), 201


@app.route("/users", methods=["GET"])
def get_users():
    conn = get_db_connection()
    users = conn.execute("SELECT id, name, email FROM users ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(u) for u in users]), 200


@app.route("/users/<int:user_id>", methods=["GET"])
def get_user(user_id):
    conn = get_db_connection()
    user = conn.execute(
        "SELECT id, name, email FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    conn.close()

    if user is None:
        return jsonify({"error": "Usuario no encontrado"}), 404

    return jsonify(dict(user)), 200


@app.route("/users/<int:user_id>", methods=["PUT"])
def update_user(user_id):
    data = request.get_json(silent=True) or {}

    name = data.get("name")
    email = data.get("email")

    if not name or not email:
        return jsonify({"error": "Faltan campos obligatorios: name, email"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "UPDATE users SET name = ?, email = ? WHERE id = ?",
            (name, email, user_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "El email ya está registrado"}), 409

    if cursor.rowcount == 0:
        conn.close()
        return jsonify({"error": "Usuario no encontrado"}), 404

    conn.close()
    return jsonify({"message": "Usuario actualizado"}), 200


@app.route("/users/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()

    if cursor.rowcount == 0:
        conn.close()
        return jsonify({"error": "Usuario no encontrado"}), 404

    conn.close()
    return jsonify({"message": "Usuario eliminado"}), 200


# -------------------------
# API CARS (CRUD)
# -------------------------

@app.route("/cars", methods=["POST"])
def create_car():
    data = request.get_json(silent=True) or {}

    user_id = data.get("user_id")
    brand = data.get("brand")
    model = data.get("model")
    year = data.get("year")
    plate = data.get("plate")

    if user_id is None or not brand or not model or year is None:
        return jsonify({"error": "Faltan campos obligatorios: user_id, brand, model, year"}), 400

    try:
        user_id = int(user_id)
        year = int(year)
    except (ValueError, TypeError):
        return jsonify({"error": "user_id y year deben ser numéricos"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    user_exists = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if user_exists is None:
        conn.close()
        return jsonify({"error": "Usuario no encontrado"}), 404

    cursor.execute("""
        INSERT INTO cars (user_id, brand, model, year, plate)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, brand, model, year, plate))
    conn.commit()
    car_id = cursor.lastrowid
    conn.close()

    return jsonify({"message": "Coche creado", "id": car_id}), 201


@app.route("/cars", methods=["GET"])
def get_cars():
    conn = get_db_connection()
    cars = conn.execute("""
        SELECT
            cars.id,
            cars.user_id,
            users.name AS user_name,
            cars.brand,
            cars.model,
            cars.year,
            cars.plate
        FROM cars
        JOIN users ON users.id = cars.user_id
        ORDER BY cars.id DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(c) for c in cars]), 200


@app.route("/cars/<int:car_id>", methods=["GET"])
def get_car(car_id):
    conn = get_db_connection()
    car = fetch_car_with_owner(conn, car_id)
    conn.close()

    if car is None:
        return jsonify({"error": "Coche no encontrado"}), 404

    return jsonify(dict(car)), 200


@app.route("/cars/<int:car_id>", methods=["PUT"])
def update_car(car_id):
    data = request.get_json(silent=True) or {}

    brand = data.get("brand")
    model = data.get("model")
    year = data.get("year")
    plate = data.get("plate")

    if not brand or not model or year is None:
        return jsonify({"error": "Faltan campos obligatorios: brand, model, year"}), 400

    try:
        year = int(year)
    except (ValueError, TypeError):
        return jsonify({"error": "year debe ser numérico"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE cars
        SET brand = ?, model = ?, year = ?, plate = ?
        WHERE id = ?
    """, (brand, model, year, plate, car_id))
    conn.commit()

    if cursor.rowcount == 0:
        conn.close()
        return jsonify({"error": "Coche no encontrado"}), 404

    conn.close()
    return jsonify({"message": "Coche actualizado"}), 200


@app.route("/cars/<int:car_id>", methods=["DELETE"])
def delete_car(car_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM cars WHERE id = ?", (car_id,))
    conn.commit()

    if cursor.rowcount == 0:
        conn.close()
        return jsonify({"error": "Coche no encontrado"}), 404

    conn.close()
    return jsonify({"message": "Coche eliminado"}), 200


# -------------------------
# API SERVICE RECORDS (CRUD)
# -------------------------

@app.route("/service-records", methods=["GET"])
def get_service_records():
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT id, car_id, service_type, service_date, mileage, cost
        FROM service_records
        ORDER BY id DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows]), 200


@app.route("/service-records/<int:record_id>", methods=["GET"])
def get_service_record(record_id):
    conn = get_db_connection()
    row = conn.execute("""
        SELECT id, car_id, service_type, service_date, mileage, cost
        FROM service_records
        WHERE id = ?
    """, (record_id,)).fetchone()
    conn.close()

    if row is None:
        return jsonify({"error": "Service record no encontrado"}), 404

    return jsonify(dict(row)), 200


@app.route("/service-records", methods=["POST"])
def create_service_record_general():
    data = request.get_json(silent=True) or {}

    car_id = data.get("car_id")
    service_type = data.get("service_type")
    service_date = data.get("service_date")
    mileage = data.get("mileage")
    cost = data.get("cost")

    if car_id is None or not service_type or not service_date or mileage is None or cost is None:
        return jsonify({"error": "Faltan campos: car_id, service_type, service_date, mileage, cost"}), 400

    try:
        car_id = int(car_id)
        mileage = int(mileage)
        cost = float(cost)
    except (ValueError, TypeError):
        return jsonify({"error": "car_id/mileage deben ser int y cost debe ser número"}), 400

    conn = get_db_connection()
    car_exists = conn.execute("SELECT id FROM cars WHERE id = ?", (car_id,)).fetchone()
    if car_exists is None:
        conn.close()
        return jsonify({"error": "Coche no encontrado"}), 404

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO service_records (car_id, service_type, service_date, mileage, cost)
        VALUES (?, ?, ?, ?, ?)
    """, (car_id, service_type, service_date, mileage, cost))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()

    return jsonify({"message": "Service record creado", "id": new_id}), 201


@app.route("/service-records/<int:record_id>", methods=["PUT"])
def update_service_record(record_id):
    data = request.get_json(silent=True) or {}

    service_type = data.get("service_type")
    service_date = data.get("service_date")
    mileage = data.get("mileage")
    cost = data.get("cost")

    if not service_type or not service_date or mileage is None or cost is None:
        return jsonify({"error": "Faltan campos: service_type, service_date, mileage, cost"}), 400

    try:
        mileage = int(mileage)
        cost = float(cost)
    except (ValueError, TypeError):
        return jsonify({"error": "mileage debe ser int y cost debe ser número"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE service_records
        SET service_type = ?, service_date = ?, mileage = ?, cost = ?
        WHERE id = ?
    """, (service_type, service_date, mileage, cost, record_id))
    conn.commit()

    if cursor.rowcount == 0:
        conn.close()
        return jsonify({"error": "Service record no encontrado"}), 404

    conn.close()
    return jsonify({"message": "Service record actualizado"}), 200


@app.route("/service-records/<int:record_id>", methods=["DELETE"])
def delete_service_record(record_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM service_records WHERE id = ?", (record_id,))
    conn.commit()

    if cursor.rowcount == 0:
        conn.close()
        return jsonify({"error": "Service record no encontrado"}), 404

    conn.close()
    return jsonify({"message": "Service record eliminado"}), 200


# -------------------------
# DÍA 3: SERVICE RECORDS (Templates + POST por car_id)
# -------------------------

@app.route("/view/cars/<int:car_id>/services", methods=["GET"])
def view_car_services(car_id):
    conn = get_db_connection()

    car = fetch_car_with_owner(conn, car_id)
    if car is None:
        conn.close()
        return "Car not found", 404

    services = conn.execute("""
        SELECT id, car_id, service_type, service_date, mileage, cost
        FROM service_records
        WHERE car_id = ?
        ORDER BY service_date DESC
    """, (car_id,)).fetchall()

    conn.close()
    return render_template("services/service_records.html", car=car, services=services)


@app.route("/cars/<int:car_id>/services", methods=["POST"])
def create_service_record_by_car(car_id):
    """
    Crear service record para un coche.
    - Template (form-data): redirige a /view/cars/<id>/services
    - Postman (JSON): responde JSON 201
    """
    data_json = request.get_json(silent=True)

    if data_json:
        service_type = (data_json.get("service_type") or "").strip()
        service_date = (data_json.get("service_date") or "").strip()
        mileage = data_json.get("mileage")
        cost = data_json.get("cost")
    else:
        service_type = (request.form.get("service_type") or "").strip()
        service_date = (request.form.get("service_date") or "").strip()
        mileage = (request.form.get("mileage") or "").strip()
        cost = (request.form.get("cost") or "").strip()

    if not service_type or not service_date or not str(mileage).strip() or not str(cost).strip():
        if data_json:
            return jsonify({"error": "Faltan campos: service_type, service_date, mileage, cost"}), 400
        return "Faltan campos del formulario", 400

    try:
        mileage = int(mileage)
        cost = float(cost)
    except (ValueError, TypeError):
        if data_json:
            return jsonify({"error": "mileage debe ser int y cost debe ser número"}), 400
        return "Mileage y cost deben ser numéricos", 400

    conn = get_db_connection()

    car_exists = conn.execute("SELECT id FROM cars WHERE id = ?", (car_id,)).fetchone()
    if car_exists is None:
        conn.close()
        if data_json:
            return jsonify({"error": "Coche no encontrado"}), 404
        return "Car not found", 404

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO service_records (car_id, service_type, service_date, mileage, cost)
        VALUES (?, ?, ?, ?, ?)
    """, (car_id, service_type, service_date, mileage, cost))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()

    if data_json:
        return jsonify({"message": "Service record creado", "id": new_id}), 201

    return redirect(url_for("view_car_services", car_id=car_id))


# -------------------------
# ✅ API CAR DOCUMENTS (OPCIONAL PARA POSTMAN)
# -------------------------

@app.route("/car-documents", methods=["GET"])
def get_car_documents():
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT id, car_id, doc_type, folio, expires_at, notes
        FROM car_documents
        ORDER BY id DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows]), 200


@app.route("/car-documents/<int:doc_id>", methods=["GET"])
def get_car_document(doc_id):
    conn = get_db_connection()
    row = fetch_document(conn, doc_id)
    conn.close()

    if row is None:
        return jsonify({"error": "Documento no encontrado"}), 404

    return jsonify(dict(row)), 200


@app.route("/car-documents", methods=["POST"])
def create_car_document_general():
    """
    Crear documento indicando car_id (para Postman).
    Body JSON:
    { "car_id": 1, "doc_type": "...", "folio": "...", "expires_at": "YYYY-MM-DD", "notes": "..." }
    """
    data = request.get_json(silent=True) or {}

    car_id = data.get("car_id")
    doc_type = (data.get("doc_type") or "").strip()
    folio = (data.get("folio") or "").strip()
    expires_at = (data.get("expires_at") or "").strip()
    notes = (data.get("notes") or "").strip()

    if car_id is None or not doc_type or not folio or not expires_at:
        return jsonify({"error": "Faltan campos: car_id, doc_type, folio, expires_at"}), 400

    try:
        car_id = int(car_id)
    except (ValueError, TypeError):
        return jsonify({"error": "car_id debe ser numérico"}), 400

    conn = get_db_connection()
    car_exists = conn.execute("SELECT id FROM cars WHERE id = ?", (car_id,)).fetchone()
    if car_exists is None:
        conn.close()
        return jsonify({"error": "Coche no encontrado"}), 404

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO car_documents (car_id, doc_type, folio, expires_at, notes)
        VALUES (?, ?, ?, ?, ?)
    """, (car_id, doc_type, folio, expires_at, notes if notes else None))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()

    return jsonify({"message": "Documento creado", "id": new_id}), 201


@app.route("/car-documents/<int:doc_id>", methods=["PUT"])
def update_car_document(doc_id):
    data = request.get_json(silent=True) or {}

    doc_type = (data.get("doc_type") or "").strip()
    folio = (data.get("folio") or "").strip()
    expires_at = (data.get("expires_at") or "").strip()
    notes = (data.get("notes") or "").strip()

    if not doc_type or not folio or not expires_at:
        return jsonify({"error": "Faltan campos: doc_type, folio, expires_at"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE car_documents
        SET doc_type = ?, folio = ?, expires_at = ?, notes = ?
        WHERE id = ?
    """, (doc_type, folio, expires_at, notes if notes else None, doc_id))
    conn.commit()

    if cursor.rowcount == 0:
        conn.close()
        return jsonify({"error": "Documento no encontrado"}), 404

    conn.close()
    return jsonify({"message": "Documento actualizado"}), 200


# -------------------------
# ✅ DOCUMENTS (GLOBAL VIEW)
# -------------------------
@app.route("/view/documents", methods=["GET"])
def documents_page():
    conn = get_db_connection()
    documents = conn.execute("""
        SELECT
            cd.id,
            cd.car_id,
            cd.doc_type,
            cd.folio,
            cd.expires_at,
            cd.notes,
            c.brand,
            c.model,
            c.plate,
            u.name AS user_name
        FROM car_documents cd
        JOIN cars c ON c.id = cd.car_id
        JOIN users u ON u.id = c.user_id
        ORDER BY cd.expires_at DESC, cd.id DESC
    """).fetchall()
    conn.close()

    return render_template("documents/documents.html", documents=documents)


if __name__ == "__main__":
    app.run(debug=True)
