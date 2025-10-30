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
    password="12345",  # change if different
    database="parking_db"
)
cursor = db.cursor(dictionary=True)

# --- Ensure default slots exist (20 Car, 20 Bike, 20 Handicapped) ---
def ensure_default_slots():
    cursor.execute("SELECT COUNT(*) AS c FROM parking_slots")
    count = cursor.fetchone()['c']
    if count >= 60:
        return

    for i in range(1, 21):
        cursor.execute("INSERT IGNORE INTO parking_slots (slot_code, slot_type, is_handicapped, status) VALUES (%s,%s,%s,%s)",
                       (f"C{i}", 'Car', 0, 'free'))
        cursor.execute("INSERT IGNORE INTO parking_slots (slot_code, slot_type, is_handicapped, status) VALUES (%s,%s,%s,%s)",
                       (f"B{i}", 'Bike', 0, 'free'))
        cursor.execute("INSERT IGNORE INTO parking_slots (slot_code, slot_type, is_handicapped, status) VALUES (%s,%s,%s,%s)",
                       (f"H{i}", 'Handicapped', 1, 'free'))
    db.commit()

ensure_default_slots()

# --------------------- ROUTES --------------------- #

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

    # Hardcoded fallback accounts
    if not user:
        if username == 'admin' and password == 'admin123':
            user = {'username': 'admin', 'role': 'admin'}
        elif username == 'user' and password == 'user123':
            user = {'username': 'user', 'role': 'user'}

    if user:
        session['username'] = user['username']
        session['role'] = user['role']
        if user['role'] == 'admin':
            return redirect('/admin')
        else:
            return redirect('/user')
    else:
        flash("Invalid credentials", "error")
        return redirect('/')

# --- Admin Dashboard ---
@app.route('/admin')
def admin_dashboard():
    if 'role' not in session or session['role'] != 'admin':
        return redirect('/')
    
    cursor.execute("SELECT COUNT(*) AS total FROM parking_slots")
    total = cursor.fetchone()['total']

    cursor.execute("SELECT COUNT(*) AS free FROM parking_slots WHERE status='free'")
    free = cursor.fetchone()['free']

    cursor.execute("SELECT COUNT(*) AS occupied FROM parking_slots WHERE status='occupied'")
    occupied = cursor.fetchone()['occupied']

    return render_template('admin_dashboard.html',
                           username=session['username'],
                           total_slots=total,
                           free_slots=free,
                           occupied_slots=occupied)

# --- Add Vehicle (Admin only) ---
@app.route('/add_vehicle', methods=['GET', 'POST'])
def add_vehicle():
    if 'role' not in session or session['role'] != 'admin':
        return redirect('/')

    message = None
    message_type = None

    if request.method == 'POST':
        number = request.form['vehicle_number'].strip()
        owner = request.form['owner_name'].strip()
        mobile = request.form['mobile_number'].strip()
        vehicle_type = request.form['vehicle_type']
        entry_time = datetime.now()

        cursor.execute("SELECT id, slot_code FROM parking_slots WHERE status='free' AND slot_type=%s ORDER BY id ASC LIMIT 1", (vehicle_type,))
        slot = cursor.fetchone()

        if slot:
            ticket_id = f"TICKET-{int(datetime.timestamp(entry_time))}-{slot['slot_code']}"
            cursor.execute("""
                INSERT INTO vehicles (vehicle_number, owner_name, mobile_number, entry_time, slot_number, ticket_id, vehicle_type)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (number, owner, mobile, entry_time, slot['id'], ticket_id, vehicle_type))
            cursor.execute("UPDATE parking_slots SET status='occupied' WHERE id=%s", (slot['id'],))
            db.commit()
            message = f"✅ Vehicle {number} added to slot {slot['slot_code']} successfully! (Ticket: {ticket_id})"
            message_type = "success"
        else:
            message = f"⚠️ No free {vehicle_type} slots available!"
            message_type = "error"

    return render_template('add_vehicle.html', message=message, message_type=message_type)


# --- Exit Vehicle ---
# --- Exit Vehicle (Admin only) ---
@app.route('/exit_vehicle', methods=['GET', 'POST'])
def exit_vehicle():
    if 'role' not in session or session['role'] != 'admin':
        return redirect('/')

    # Confirm payment and finalize exit
    if request.method == 'POST' and request.form.get('confirm_payment') == '1':
        vehicle_id = request.form['vehicle_id']
        cursor.execute("SELECT * FROM vehicles WHERE id=%s AND exit_time IS NULL", (vehicle_id,))
        vehicle = cursor.fetchone()

        if not vehicle:
            flash("Vehicle not found or already exited.", "error")
            return redirect(url_for('exit_vehicle'))

        exit_time = datetime.now()
        hours = math.ceil((exit_time - vehicle['entry_time']).total_seconds() / 3600)
        fee = 20 + max(0, (hours - 1)) * 10

        # Update vehicle, slot, and transactions
        cursor.execute("UPDATE vehicles SET exit_time=%s, fee=%s WHERE id=%s", (exit_time, fee, vehicle_id))
        cursor.execute("UPDATE parking_slots SET status='free' WHERE id=%s", (vehicle['slot_number'],))
        cursor.execute("""
            INSERT INTO transactions (vehicle_number, entry_time, exit_time, fee)
            VALUES (%s,%s,%s,%s)
        """, (vehicle['vehicle_number'], vehicle['entry_time'], exit_time, fee))
        db.commit()

        flash(f"Vehicle {vehicle['vehicle_number']} exited. Collected ₹{fee}.", "success")
        return redirect(url_for('exit_vehicle'))

    # When admin searches for a vehicle to exit
    if request.method == 'POST' and not request.form.get('confirm_payment'):
        vehicle_number = request.form['vehicle_number'].strip()
        cursor.execute("""
            SELECT v.*, p.slot_code 
            FROM vehicles v
            JOIN parking_slots p ON v.slot_number = p.id
            WHERE v.vehicle_number=%s AND v.exit_time IS NULL
        """, (vehicle_number,))
        vehicle = cursor.fetchone()

        if not vehicle:
            flash("Vehicle not found or already exited.", "error")
            return redirect(url_for('exit_vehicle'))

        exit_time = datetime.now()
        hours = math.ceil((exit_time - vehicle['entry_time']).total_seconds() / 3600)
        fee = 20 + max(0, (hours - 1)) * 10
        return render_template('exit_confirm.html', vehicle=vehicle, fee=fee, hours=hours)

    # Default view - list all vehicles currently parked
    cursor.execute("""
        SELECT v.id, v.vehicle_number, v.owner_name, v.mobile_number, v.vehicle_type, v.entry_time, p.slot_code
        FROM vehicles v
        JOIN parking_slots p ON v.slot_number = p.id
        WHERE v.exit_time IS NULL
        ORDER BY v.entry_time ASC
    """)
    vehicles = cursor.fetchall()
    return render_template('exit_vehicle.html', vehicles=vehicles)

# --- View All Vehicles (Admin only) ---
@app.route('/view_vehicles')
def view_vehicles():
    if 'role' not in session or session['role'] != 'admin':
        return redirect('/')

    cursor.execute("""
        SELECT 
            v.id,
            v.vehicle_number,
            v.owner_name,
            v.mobile_number,
            v.vehicle_type,
            p.slot_code,
            v.entry_time
        FROM vehicles v
        JOIN parking_slots p ON v.slot_number = p.id
        WHERE v.exit_time IS NULL
        ORDER BY v.entry_time ASC
    """)
    vehicles = cursor.fetchall()
    return render_template('view_vehicles.html', vehicles=vehicles)
# --- View Transactions (Admin only) ---
@app.route('/view_transactions')
def view_transactions():
    if 'role' not in session or session['role'] != 'admin':
        return redirect('/')

    cursor.execute("""
        SELECT 
            id,
            vehicle_number,
            entry_time,
            exit_time,
            fee
        FROM transactions
        ORDER BY exit_time DESC
    """)
    transactions = cursor.fetchall()
    return render_template('view_transactions.html', transactions=transactions)
# --- Monthly Revenue (Admin only) ---
@app.route('/monthly_revenue')
def monthly_revenue():
    if 'role' not in session or session['role'] != 'admin':
        return redirect('/')

    # Get current month and year
    now = datetime.now()
    current_month = now.month
    current_year = now.year

    # Fetch all transactions from the current month
    cursor.execute("""
        SELECT 
            DATE(exit_time) AS date,
            SUM(fee) AS total_fee,
            COUNT(*) AS total_transactions
        FROM transactions
        WHERE MONTH(exit_time) = %s AND YEAR(exit_time) = %s
        GROUP BY DATE(exit_time)
        ORDER BY DATE(exit_time) ASC
    """, (current_month, current_year))
    daily_revenue = cursor.fetchall()

    # Calculate total revenue for the month
    cursor.execute("""
        SELECT SUM(fee) AS monthly_total, COUNT(*) AS total_transactions
        FROM transactions
        WHERE MONTH(exit_time) = %s AND YEAR(exit_time) = %s
    """, (current_month, current_year))
    summary = cursor.fetchone()

    monthly_total = summary['monthly_total'] or 0
    total_transactions = summary['total_transactions'] or 0

    return render_template(
        'monthly_revenue.html',
        daily_revenue=daily_revenue,
        monthly_total=monthly_total,
        total_transactions=total_transactions,
        month=now.strftime("%B"),
        year=current_year
    )


# --- User Dashboard ---
@app.route('/user', methods=['GET'])
def user_dashboard():
    if 'role' not in session or session['role'] != 'user':
        return redirect('/')

    cursor.execute("SELECT COUNT(*) AS total FROM parking_slots")
    total = cursor.fetchone()['total']
    cursor.execute("SELECT COUNT(*) AS free FROM parking_slots WHERE status='free'")
    free = cursor.fetchone()['free']
    cursor.execute("SELECT COUNT(*) AS occupied FROM parking_slots WHERE status='occupied'")
    occupied = cursor.fetchone()['occupied']

    return render_template('user_dashboard.html',
                           username=session['username'],
                           total_slots=total,
                           free_slots=free,
                           occupied_slots=occupied)

# --- View Ticket (User search) ---
@app.route('/view_ticket', methods=['POST'])
def view_ticket():
    vehicle_number = request.form['vehicle_number'].strip()
    cursor.execute("""
        SELECT v.*, p.slot_code FROM vehicles v
        JOIN parking_slots p ON v.slot_number=p.id
        WHERE v.vehicle_number=%s
        ORDER BY v.entry_time DESC LIMIT 1
    """, (vehicle_number,))
    ticket = cursor.fetchone()

    if not ticket:
        flash("No ticket found for that vehicle number.", "error")
        return redirect(url_for('user_dashboard'))

    return render_template('ticket.html', ticket=ticket)

# --- Logout ---
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# --- Run ---
if __name__ == '__main__':
    app.run(debug=True)
