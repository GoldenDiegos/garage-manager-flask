from flask import Flask, jsonify, request, render_template, redirect, url_for
import sqlite3

app = Flask(__name__)


DATABASE = "database.db"


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


def row_to_dict(row):
    return dict(row) if row is not None else None


init_db()


# -------------------------
# VISTAS (TEMPLATES)
# -------------------------

@app.route("/")
def home():
    return redirect(url_for("cars_page"))


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
# API USERS (CRUD)
# -------------------------

@app.route("/users", methods=["POST"])
def create_user():
    data = request.get_json(silent=True) or {}

    name = data.get("name")
    email = data.get("email")
    password = data.get("password")

    if not name or not email or not password:
        return jsonify({"error": "Faltan campos obligatorios: name, email, password"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
            (name, email, password),
        )
        conn.commit()
        user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "El email ya está registrado"}), 409

    conn.close()
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

    # Verifica usuario
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
# API SERVICE RECORDS (CRUD COMPLETO PARA POSTMAN)
# -------------------------

@app.route("/service-records", methods=["GET"])
def get_service_records():
    """
    Lista todos los service records (útil para Postman).
    """
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT
            sr.id,
            sr.car_id,
            sr.service_type,
            sr.service_date,
            sr.mileage,
            sr.cost
        FROM service_records sr
        ORDER BY sr.id DESC
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
    """
    Crear service record indicando car_id (para Postman).
    Body JSON:
    { "car_id": 1, "service_type": "...", "service_date": "YYYY-MM-DD", "mileage": 123, "cost": 99.9 }
    """
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
    """
    Vista por carro: historial de servicios.
    Template: templates/services/service_records.html
    """
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

    print("CONTENT-TYPE:", request.content_type)
    print("RAW DATA:", request.get_data(as_text=True))
    print("FORM:", dict(request.form))

    data_json = request.get_json(silent=True)

    if data_json:
        service_type = (data_json.get("service_type") or "").strip()
        service_date = (data_json.get("service_date") or "").strip()
        mileage = data_json.get("mileage")
        cost = data_json.get("cost")
    else:
        service_type = (request.form.get("service_type") or request.form.get("TipoServicio") or "").strip()
        service_date = (request.form.get("service_date") or request.form.get("Fecha") or request.form.get("fecha") or "").strip()
        mileage = (request.form.get("mileage") or request.form.get("Kilometraje") or request.form.get("kilometraje") or "").strip()
        cost = (request.form.get("cost") or request.form.get("costo") or request.form.get("Costo") or "").strip()

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



if __name__ == "__main__":
    app.run(debug=True)
