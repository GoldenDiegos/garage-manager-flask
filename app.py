from flask import Flask, jsonify, request, render_template
import sqlite3

app = Flask(__name__)

# Base de datos en la raíz (fiel al estilo del profe)
DATABASE = "database.db"


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


# -------------------------
# VISTAS (TEMPLATES)
# -------------------------

@app.route("/")
def home():
    return render_template("home.html")


# Antes estaba en /cars, pero ahora /cars lo usa la API (estilo profe)
# Tus templates NO cambian; solo cambió la URL para verlos.
@app.route("/view/cars")
def cars_page():
    return render_template("cars/cars.html")


@app.route("/init-db")
def initialize_database():
    init_db()
    return "Base de datos inicializada correctamente"


# -------------------------
# API USERS (CRUD) - ESTILO PROFE
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
    users = conn.execute("SELECT id, name, email FROM users").fetchall()
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

    if not user_id or not brand or not model or not year:
        return jsonify({
            "error": "Faltan campos obligatorios: user_id, brand, model, year"
        }), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO cars (user_id, brand, model, year, plate)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, brand, model, year, plate))
        conn.commit()
        car_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "Usuario no válido"}), 400

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

    car = conn.execute("""
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

    if not brand or not model or not year:
        return jsonify({
            "error": "Faltan campos obligatorios: brand, model, year"
        }), 400

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

if __name__ == "__main__":
    app.run(debug=True)
