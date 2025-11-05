import os
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path)

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime
import psycopg2
from urllib.parse import urlparse


app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY", "fallback_secret")

# === CONFIG ===
# Railway provides DATABASE_URL, but also support individual variables for local dev
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # Parse Railway's DATABASE_URL
    url = urlparse(DATABASE_URL)
    DB_CONFIG = {
        "host": url.hostname,
        "database": url.path[1:],  # Remove leading slash
        "user": url.username,
        "password": url.password,
        "port": url.port or 5432
    }
else:
    # Fallback to individual environment variables (for local development)
    DB_CONFIG = {
        "host": os.getenv("DB_HOST", "localhost"),
        "database": os.getenv("DB_NAME", "warehouse_db"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", ""),
        "port": os.getenv("DB_PORT", "5432")
    }


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


# ============================================
#  ⛑️ Helper function: Get warehouse data for display
# ============================================
def get_location_data():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT serial_number, kanban_location, status, last_update_in, last_update_out
        FROM warehouse_db
    """)
    rows = cur.fetchall()
    conn.close()

    location_data = {}
    for serial_number, kanban_location, status, last_update_in, last_update_out in rows:
        if not kanban_location:
            continue
        location_data[kanban_location] = {
            'serial': serial_number or "N/A",
            'status': status or "Out Storage",
            'last_update_in': str(last_update_in) if last_update_in else None,
            'last_update_out': str(last_update_out) if last_update_out else None
        }

    return rows, location_data


# ============================================
# Routes
# ============================================

# @app.route("/")
# def index():
#     conn = get_conn()
#     cur = conn.cursor()
#     cur.execute("""
#         SELECT serial_number, kanban_location, status, last_update_in, last_update_out
#         FROM warehouse_db
#     """)
#     rows = cur.fetchall()
#     conn.close()
#     return render_template("index.html", items=rows)


@app.route("/", methods=["GET"])
def racking_view():
    rows, location_data = get_location_data()
    active_tab = request.args.get("tab", "registration")
    error_serial = request.args.get("error_serial")

    return render_template("warehouse-racking.html",
                           items=rows,
                           location_data=location_data,
                           active_tab=active_tab,
                           error_serial=error_serial)


# ============================================
# Search route
# ============================================
@app.route("/search", methods=["POST"])
def search():
    serial_number = request.form.get("serial_number")

    if not serial_number:
        flash("No serial number provided.")
        return redirect(url_for("racking_view", tab="search"))

    rows, location_data = get_location_data()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT serial_number, kanban_location, status, last_update_in, last_update_out
        FROM warehouse_db
        WHERE serial_number = %s
    """, (serial_number,))
    row = cur.fetchone()

    if not row:
        cur.execute("""
            SELECT serial_number, kanban_location, status, last_update_in, last_update_out
            FROM warehouse_db_old
            WHERE serial_number = %s
        """, (serial_number,))
        row = cur.fetchone()

    conn.close()

    if row:
        flash(f"Serial number {serial_number} found.", "success")
        return render_template(
            "warehouse-racking.html",
            search_result=row,
            location_data=location_data,
            items=rows,
            active_tab="search"
        )
    else:
        flash(f"Serial number {serial_number} not found!", "error")
        return redirect(url_for("racking_view", tab="search", error_serial=serial_number))


# ============================================
# Add item route
# ============================================
@app.route("/add_item", methods=["POST"])
def add_item():
    serial_number = request.form.get("serial_number")
    kanban_location = request.form.get("kanban_location")
    status = request.form.get("Status")
    now = datetime.now()

    if not serial_number or not kanban_location or not status:
        flash("❌ Please fill in all fields!", "error")
        return redirect(url_for("index"))

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT serial_number, kanban_location, status
        FROM warehouse_db
        WHERE serial_number = %s
    """, (serial_number,))
    existing = cur.fetchone()

    try:
        if existing:
            if status == "In Storage":
                cur.execute("""
                    SELECT COUNT(*) FROM warehouse_db
                    WHERE kanban_location = %s AND status = 'In Storage' AND serial_number != %s
                """, (kanban_location, serial_number))
                occupied = cur.fetchone()[0]
                if occupied > 0:
                    flash(f"❌ Location '{kanban_location}' is already occupied!", "error")
                    return redirect(url_for("index"))

                cur.execute("""
                    UPDATE warehouse_db
                    SET kanban_location = %s, status = %s, last_update_in = %s, last_update_out = NULL
                    WHERE serial_number = %s
                """, (kanban_location, status, now, serial_number))
                flash(f"✅ Serial {serial_number} moved to {kanban_location}!", "success")
            else:
                cur.execute("""
                    UPDATE warehouse_db
                    SET status = %s, last_update_out = %s
                    WHERE serial_number = %s
                """, (status, now, serial_number))
                flash(f"✅ Serial {serial_number} marked as Out Storage!", "success")
        else:
            cur.execute("""
                INSERT INTO warehouse_db (serial_number, kanban_location, status, last_update_in, last_update_out)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                serial_number,
                kanban_location,
                status,
                now if status == "In Storage" else None,
                now if status != "In Storage" else None
            ))
            flash(f"✅ Serial {serial_number} added to {kanban_location}!", "success")

        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error: {e}", "error")
    finally:
        conn.close()

    return redirect(url_for("index"))


# ============================================
# Update status route
# ============================================
@app.route("/update_status/<serial>", methods=["POST"])
def update_status(serial):
    new_status = request.form.get("status")
    now = datetime.now()

    if not new_status:
        flash("❌ Please select a status!", "error")
        return redirect(url_for("index"))

    conn = get_conn()
    cur = conn.cursor()

    try:
        if new_status == "In Storage":
            cur.execute("""
                UPDATE warehouse_db
                SET status = %s, last_update_in = %s
                WHERE serial_number = %s
            """, (new_status, now, serial))
        else:
            cur.execute("""
                UPDATE warehouse_db
                SET status = %s, last_update_out = %s
                WHERE serial_number = %s
            """, (new_status, now, serial))

        conn.commit()
        flash(f"✅ Serial {serial} updated to {new_status}!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error: {e}", "error")
    finally:
        conn.close()

    return redirect(url_for("index"))


# ============================================
# Add item for racking page
# ============================================
@app.route("/add_item_racking", methods=["POST"])
def add_item_racking():
    serial_number = request.form.get("serial_number", "").strip()
    kanban_location = request.form.get("kanban_location", "").strip()
    status = "In Storage"
    now = datetime.now()

    if not serial_number or not kanban_location:
        flash("❌ Please fill in all fields!", "error")
        return redirect(url_for("racking_view", tab="registration"))

    confirmed = request.form.get("confirmed", "no")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT serial_number FROM warehouse_db
        WHERE kanban_location = %s AND status = 'In Storage'
    """, (kanban_location,))
    existing_at_location = cur.fetchone()

    if existing_at_location and existing_at_location[0] != serial_number:
        conn.close()
        flash(f"❌ Location '{kanban_location}' is occupied!", "error")
        return redirect(url_for("racking_view", tab="registration"))

    cur.execute("""
        SELECT serial_number, kanban_location, status
        FROM warehouse_db
        WHERE serial_number = %s
    """, (serial_number,))
    existing = cur.fetchone()

    try:
        if existing:
            old_location, old_status = existing[1], existing[2]
            if old_location != kanban_location and confirmed != "yes":
                conn.close()
                rows, location_data = get_location_data()
                flash(f"⚠️ Serial {serial_number} already exists at {old_location}. Confirm to move.", "warning")
                return render_template("warehouse-racking.html",
                                       confirm_serial=serial_number,
                                       confirm_location=kanban_location,
                                       confirm_status=status,
                                       active_tab="registration",
                                       location_data=location_data,
                                       items=rows)

            cur.execute("""
                UPDATE warehouse_db
                SET kanban_location = %s, status = %s, last_update_in = %s, last_update_out = NULL
                WHERE serial_number = %s
            """, (kanban_location, status, now, serial_number))
            flash(f"✅ Serial {serial_number} moved to {kanban_location}!", "success")
        else:
            cur.execute("""
                INSERT INTO warehouse_db (serial_number, kanban_location, status, last_update_in, last_update_out)
                VALUES (%s, %s, %s, %s, %s)
            """, (serial_number, kanban_location, status, now, None))
            flash(f"✅ Serial {serial_number} registered!", "success")

        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error: {e}", "error")
    finally:
        conn.close()

    return redirect(url_for("racking_view", tab="registration"))


# ============================================
# Register dummy slot
# ============================================
@app.route("/register_dummy", methods=["POST"])
def register_dummy():
    kanban_location = request.form.get("kanban_location", "").strip()
    if not kanban_location:
        flash("❌ Please select a location!", "error")
        return redirect(url_for("racking_view", tab="registration"))

    now = datetime.now()
    serial_number = f"Dummy_{kanban_location}"
    status = "Reserved"

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT serial_number, status FROM warehouse_db
            WHERE kanban_location = %s
        """, (kanban_location,))
        existing = cur.fetchone()

        if existing:
            if existing[0].startswith("Dummy_"):
                cur.execute("DELETE FROM warehouse_db WHERE kanban_location = %s", (kanban_location,))
                flash(f"✅ Dummy removed from {kanban_location}!", "success")
            else:
                flash(f"❌ Location {kanban_location} occupied by {existing[0]}!", "error")
                conn.close()
                return redirect(url_for("racking_view", tab="registration"))
        else:
            cur.execute("""
                INSERT INTO warehouse_db (serial_number, kanban_location, status, last_update_in)
                VALUES (%s, %s, %s, %s)
            """, (serial_number, kanban_location, status, now))
            flash(f"✅ Dummy pallet reserved at {kanban_location}!", "success")

        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error: {e}", "error")
    finally:
        conn.close()

    return redirect(url_for("racking_view", tab="registration"))


# ============================================
# Push out (archive)
# ============================================
@app.route("/push_out", methods=["POST"])
def push_out():
    serial_number = request.form.get("serial_number")
    if not serial_number:
        flash("No serial number provided.")
        return redirect(url_for("racking_view"))

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT serial_number, kanban_location, status, last_update_in
            FROM warehouse_db
            WHERE serial_number = %s
        """, (serial_number,))
        record = cur.fetchone()

        if not record:
            flash(f"Serial number {serial_number} not found.")
            conn.close()
            return redirect(url_for("racking_view", tab="search"))

        new_update_out = datetime.now()

        cur.execute("SELECT serial_number FROM warehouse_db_old WHERE serial_number = %s", (serial_number,))
        exists = cur.fetchone()

        if exists:
            cur.execute("""
                UPDATE warehouse_db_old
                SET kanban_location = %s, status = 'Out Storage',
                    last_update_in = %s, last_update_out = %s
                WHERE serial_number = %s
            """, (record[1], record[3], new_update_out, serial_number))
        else:
            cur.execute("""
                INSERT INTO warehouse_db_old (serial_number, kanban_location, status, last_update_in, last_update_out)
                VALUES (%s, %s, 'Out Storage', %s, %s)
            """, (record[0], record[1], record[3], new_update_out))

        cur.execute("DELETE FROM warehouse_db WHERE serial_number = %s", (serial_number,))
        conn.commit()
        flash(f"✅ Serial {serial_number} archived.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error: {e}", "error")
    finally:
        conn.close()

    return redirect(url_for("racking_view", tab="registration"))


# ============================================
# Debug routes
# ============================================
@app.route("/debug_db")
def debug_db():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        tables = [t[0] for t in cur.fetchall()]
        result = "<h2>Database Tables</h2>"
        for table in tables:
            result += f"<h3>{table}</h3><ul>"
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = %s
            """, (table,))
            cols = [c[0] for c in cur.fetchall()]
            result += "".join(f"<li>{c}</li>" for c in cols)
            result += "</ul>"
        conn.close()
        return result
    except Exception as e:
        return f"Debug error: {e}"


@app.route("/debug_locations")
def debug_locations():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT serial_number, kanban_location, status FROM warehouse_db")
    rows = cur.fetchall()
    conn.close()
    result = f"<h2>Total Records: {len(rows)}</h2><table border='1'><tr><th>Serial</th><th>Location</th><th>Status</th></tr>"
    for row in rows:
        result += f"<tr><td>{row[0]}</td><td>{row[1]}</td><td>{row[2]}</td></tr>"
    result += "</table>"
    return result


@app.route('/api/warehouse_data')
def get_warehouse_data_api():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT serial_number, kanban_location, status, last_update_in, last_update_out FROM warehouse_db")
    items = cur.fetchall()
    conn.close()

    warehouse_data = {}
    for serial, location, status, tin, tout in items:
        warehouse_data[location] = {
            'serial': serial,
            'status': status,
            'last_update_in': str(tin) if tin else None,
            'last_update_out': str(tout) if tout else None
        }

    return jsonify(warehouse_data)


# ============================================
# Run
# ============================================
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)