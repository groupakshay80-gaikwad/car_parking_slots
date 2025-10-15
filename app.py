from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime
import math
import mysql.connector

app = Flask(__name__)
app.secret_key = "secret123"

# --- MySQL Connection ---
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="12345",  # change your password
    database="parking_db"
)
cursor = db.cursor(dictionary=True)

# --- Routes ---

@app.route('/')
def home():
    return render_template('index.html')

# --- Login ---
@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']

    cursor.execute("SELECT * FROM users WHERE username=%s AND password=%s", (username, password))
    user = cursor.fetchone()

    if user:
        session['username'] = user['username']
        session['role'] = user['role']

        if user['role'] == 'admin':
            return redirect('/admin')
        else:
            return redirect('/user')
    else:
        return "Invalid credentials"

# --- Admin Dashboard ---
@app.route('/admin')
def admin_dashboard():
    if 'username' in session and session['role'] == 'admin':
        return render_template('admin_dashboard.html', username=session['username'])
    return redirect('/')

# --- User Dashboard ---
@app.route('/user', methods=['GET', 'POST'])
def user_dashboard():
    if 'username' in session and session['role'] == 'user':
        search = request.form.get('search', '')

        query = """
            SELECT 
                v.vehicle_number, 
                v.owner_name, 
                v.entry_time, 
                v.exit_time, 
                v.fee, 
                v.ticket_id, 
                p.slot_code
            FROM vehicles v
            JOIN parking_slots p ON v.slot_number = p.id
            WHERE v.ticket_id IS NOT NULL
        """

        params = ()
        if search.strip():
            query += " AND v.vehicle_number LIKE %s"
            params = (f"%{search}%",)

        query += " ORDER BY v.entry_time DESC"

        cursor.execute(query, params)
        tickets = cursor.fetchall()

        return render_template(
            'user_dashboard.html',
            username=session['username'],
            tickets=tickets,
            search=search
        )

    return redirect('/')


# --- Add Vehicle (Admin Only) ---
@app.route('/add_vehicle', methods=['GET', 'POST'])
def add_vehicle():
    if 'role' in session and session['role'] != 'admin':
        return "Access denied."

    message = None
    message_type = None

    if request.method == 'POST':
        number = request.form['vehicle_number']
        owner = request.form['owner_name']
        entry_time = datetime.now()

        # --- Find first free slot ---
        cursor.execute("SELECT id, slot_code FROM parking_slots WHERE status='free' ORDER BY id ASC LIMIT 1")
        slot = cursor.fetchone()

        if slot:
            # --- Generate ticket ID ---
            ticket_id = f"TICKET-{int(datetime.timestamp(entry_time))}"

            # --- Insert vehicle ---
            cursor.execute(
                "INSERT INTO vehicles (vehicle_number, owner_name, entry_time, slot_number, ticket_id) VALUES (%s,%s,%s,%s,%s)",
                (number, owner, entry_time, slot['id'], ticket_id)
            )

            # --- Mark slot as occupied ---
            cursor.execute("UPDATE parking_slots SET status='occupied' WHERE id=%s", (slot['id'],))
            db.commit()
            message = f"Vehicle {number} successfully added to parking slot {slot['slot_code']}! Ticket ID: {ticket_id}"
            message_type = "success"
        else:
            message = "No free parking slots available at the moment."
            message_type = "error"

    return render_template('add_vehicle.html', message=message, message_type=message_type)

# --- Exit Vehicle ---
@app.route('/exit_vehicle', methods=['GET', 'POST'])
def exit_vehicle():
    message = None

    if request.method == 'POST':
        number = request.form.get('vehicle_number', '').strip()
        if not number:
            message = "Please enter a vehicle number."
            return redirect(url_for('exit_vehicle', message=message))

        cursor = db.cursor(dictionary=True, buffered=True)

        # Find the active vehicle
        cursor.execute("SELECT * FROM vehicles WHERE vehicle_number=%s AND exit_time IS NULL", (number,))
        vehicle = cursor.fetchone()

        if vehicle:
            exit_time = datetime.now()
            entry_time = vehicle['entry_time']
            hours = math.ceil((exit_time - entry_time).total_seconds() / 3600)
            fee = 20 + (hours - 1) * 10  # Fee logic

            # Update vehicle details
            cursor.execute("""
                UPDATE vehicles SET exit_time=%s, fee=%s WHERE id=%s
            """, (exit_time, fee, vehicle['id']))

            # Free up the slot
            cursor.execute("UPDATE parking_slots SET status='free' WHERE id=%s", (vehicle['slot_number'],))

            # Insert transaction record
            cursor.execute("""
                INSERT INTO transactions (vehicle_number, entry_time, exit_time, fee)
                VALUES (%s, %s, %s, %s)
            """, (number, entry_time, exit_time, fee))

            db.commit()
            message = f"✅ Vehicle {number} exited successfully. Fee: ₹{fee}"
        else:
            message = "❌ Vehicle not found or already exited."

        cursor.close()
        return redirect(url_for('exit_vehicle', message=message))

    # GET request: show active vehicles
    cursor = db.cursor(dictionary=True, buffered=True)
    cursor.execute("""
        SELECT v.vehicle_number, v.owner_name, p.slot_code, v.entry_time
        FROM vehicles v
        JOIN parking_slots p ON v.slot_number = p.id
        WHERE v.exit_time IS NULL
    """)
    vehicles = cursor.fetchall()
    cursor.close()

    message = request.args.get('message')
    return render_template('exit_vehicle.html', vehicles=vehicles, message=message)




    # GET request: show all currently parked vehicles
    cursor.execute(
        "SELECT v.vehicle_number, v.entry_time, p.slot_code "
        "FROM vehicles v "
        "JOIN parking_slots p ON v.slot_number=p.id "
        "WHERE v.exit_time IS NULL "
        "ORDER BY v.entry_time ASC"
    )
    vehicles = cursor.fetchall()

    # Get message from redirect if any
    message = request.args.get('message')
    return render_template('exit_vehicle.html', vehicles=vehicles, message=message)


    # GET request: show active vehicles with optional search
    search = request.args.get('search', '')
    if search:
        cursor.execute("""
            SELECT v.vehicle_number, v.owner_name, p.slot_code, v.entry_time
            FROM vehicles v
            JOIN parking_slots p ON v.slot_number = p.id
            WHERE v.exit_time IS NULL AND v.vehicle_number LIKE %s
            ORDER BY v.entry_time ASC
        """, ('%' + search + '%',))
    else:
        cursor.execute("""
            SELECT v.vehicle_number, v.owner_name, p.slot_code, v.entry_time
            FROM vehicles v
            JOIN parking_slots p ON v.slot_number = p.id
            WHERE v.exit_time IS NULL
            ORDER BY v.entry_time ASC
        """)

    vehicles = cursor.fetchall()
    message = request.args.get('message', '')
    return render_template('exit_vehicle.html', vehicles=vehicles, search=search, message=message)


# --- View Vehicles (Admin) ---
@app.route('/view_vehicles')
def view_vehicles():
    cursor.execute("""
        SELECT v.vehicle_number, v.owner_name, v.entry_time, v.ticket_id, p.slot_code
        FROM vehicles v
        JOIN parking_slots p ON v.slot_number=p.id
        WHERE v.exit_time IS NULL
    """)
    vehicles = cursor.fetchall()
    return render_template('view_vehicles.html', vehicles=vehicles)

# --- View Transactions (Admin) ---
@app.route('/view_transactions')
def view_transactions():
    cursor.execute("SELECT * FROM transactions")
    transactions = cursor.fetchall()
    return render_template('view_transactions.html', transactions=transactions)

# --- Logout ---
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == '__main__':
    app.run(debug=True)
