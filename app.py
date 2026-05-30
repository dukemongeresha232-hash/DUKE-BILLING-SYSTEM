from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
from functools import wraps
import json
import os
import random
import string
import qrcode

app = Flask(__name__)
app.secret_key = 'your-secret-key'

DATA_DIR = "data"
BILLS_FILE = os.path.join(DATA_DIR, "bills.json")
USERS_FILE = os.path.join(DATA_DIR, "active_users.json")
STAFF_FILE = os.path.join(DATA_DIR, "users.json")
QR_DIR = os.path.join("static", "qrcodes")

for directory in [DATA_DIR, QR_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)

def load_data(file):
    if os.path.exists(file):
        with open(file, 'r') as f:
            return json.load(f)
    return []

def save_data(file, data):
    with open(file, 'w') as f:
        json.dump(data, f, indent=4)

def generate_wifi_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def generate_qr_code(data, filename):
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img_path = os.path.join(QR_DIR, filename)
    img.save(img_path)
    return f"/static/qrcodes/{filename}"

def init_admin():
    users = load_data(STAFF_FILE)
    if not users:
        users.append({'id': 1, 'username': 'admin', 'password': 'admin123', 'role': 'admin', 'name': 'Admin'})
        save_data(STAFF_FILE, users)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        users = load_data(STAFF_FILE)
        user = next((u for u in users if u['username'] == request.form['username'] and u['password'] == request.form['password']), None)
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['name'] = user['name']
            return redirect(url_for('dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    bills = load_data(BILLS_FILE)
    active = load_data(USERS_FILE)
    total_revenue = sum(b.get('price', 0) for b in bills)
    today_revenue = sum(b.get('price', 0) for b in bills if b.get('date', '').startswith(datetime.now().strftime('%Y-%m-%d')))
    return render_template('dashboard.html', total_revenue=total_revenue, today_revenue=today_revenue, active_count=len(active), total_bills=len(bills), username=session.get('name'))

@app.route('/new-bill', methods=['GET', 'POST'])
@login_required
def new_bill():
    if request.method == 'POST':
        customer_name = request.form['customer_name']
        plan_type = request.form['plan_type']
        price = float(request.form['price'])
        code = generate_wifi_code()
        qr_path = generate_qr_code(f"WIFI:S:{code};T:WPA;P:{code};;", f"{code}.png")
        
        if plan_type == 'time':
            hours = int(request.form['hours'])
            expiry = datetime.now() + timedelta(hours=hours)
            bill = {'bill_no': f"WIFI-{datetime.now().strftime('%Y%m%d%H%M%S')}", 'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'customer': customer_name, 'type': 'Time-based', 'hours': hours, 'price': price, 'code': code, 'qr_code': qr_path, 'expiry': expiry.strftime('%Y-%m-%d %H:%M:%S'), 'staff': session.get('username')}
            active_user = {'code': code, 'customer': customer_name, 'expiry': expiry.strftime('%Y-%m-%d %H:%M:%S'), 'type': 'time', 'qr_code': qr_path}
        else:
            mb = int(request.form['data_mb'])
            bill = {'bill_no': f"WIFI-{datetime.now().strftime('%Y%m%d%H%M%S')}", 'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'customer': customer_name, 'type': 'Data-based', 'data_mb': mb, 'price': price, 'code': code, 'qr_code': qr_path, 'staff': session.get('username')}
            active_user = {'code': code, 'customer': customer_name, 'data_remaining': mb, 'type': 'data', 'qr_code': qr_path}
        
        bills = load_data(BILLS_FILE)
        bills.append(bill)
        save_data(BILLS_FILE, bills)
        active = load_data(USERS_FILE)
        active.append(active_user)
        save_data(USERS_FILE, active)
        return render_template('receipt.html', bill=bill)
    return render_template('new_bill.html')

@app.route('/active-users')
@login_required
def active_users():
    users = load_data(USERS_FILE)
    return render_template('active_users.html', users=users)

@app.route('/delete-user/<code>')
@login_required
def delete_user(code):
    users = load_data(USERS_FILE)
    users = [u for u in users if u['code'] != code]
    save_data(USERS_FILE, users)
    return redirect(url_for('active_users'))

@app.route('/sales-report')
@login_required
def sales_report():
    bills = load_data(BILLS_FILE)
    days = int(request.args.get('days', 30))
    cutoff = datetime.now() - timedelta(days=days)
    filtered = [b for b in bills if datetime.strptime(b['date'], '%Y-%m-%d %H:%M:%S') > cutoff]
    staff_sales = {}
    for bill in filtered:
        staff = bill.get('staff', 'unknown')
        staff_sales[staff] = staff_sales.get(staff, 0) + bill['price']
    return render_template('sales_report.html', bills=filtered, staff_sales=staff_sales, days=days, total=sum(b['price'] for b in filtered))

@app.route('/users')
@login_required
def manage_users():
    if session.get('role') != 'admin':
        return redirect(url_for('dashboard'))
    users = load_data(STAFF_FILE)
    return render_template('users.html', users=users)

@app.route('/add-user', methods=['POST'])
@login_required
def add_user():
    if session.get('role') != 'admin':
        return redirect(url_for('dashboard'))
    users = load_data(STAFF_FILE)
    new_id = max([u['id'] for u in users]) + 1 if users else 1
    users.append({'id': new_id, 'username': request.form['username'], 'password': request.form['password'], 'name': request.form['name'], 'email': request.form['email'], 'role': request.form['role']})
    save_data(STAFF_FILE, users)
    return redirect(url_for('manage_users'))

@app.route('/delete-staff/<int:user_id>')
@login_required
def delete_staff(user_id):
    if session.get('role') != 'admin' or user_id == session['user_id']:
        return redirect(url_for('dashboard'))
    users = load_data(STAFF_FILE)
    users = [u for u in users if u['id'] != user_id]
    save_data(STAFF_FILE, users)
    return redirect(url_for('manage_users'))

if __name__ == '__main__':
    init_admin()
    app.run(debug=True, port=5000)
