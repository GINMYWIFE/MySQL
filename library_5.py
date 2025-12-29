'''
Bookstore System (Based on Library 4)
Roles: Customer, Staff, Manager
Features: Shopping Cart, Orders, Inventory, Stats
'''

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_from_directory
import mysql.connector as mc
from mysql.connector import Error
import os
import datetime
import random
import uuid
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = 'bookstore_secret_key'
UPLOAD_FOLDER = 'static/covers'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

database_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '994694',
    'database': 'library', # Reusing the database, will update schema
    'connection_timeout': 5
}

def connect_():
    try:
        conn = mc.connect(**database_config)
        return conn
    except Error as e:
        print(f"Database connection failed: {e}")
        return None

def initialize_database():
    conn = connect_()
    if conn is None:
        return False
    try:
        cursor = conn.cursor()
        
        # Enable foreign key checks
        cursor.execute("SET FOREIGN_KEY_CHECKS=0")

        # Users table update: Add role and balance
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,   
                nickname VARCHAR(100),
                gender ENUM('男', '女', '其他') DEFAULT '其他',
                role ENUM('customer', 'staff', 'manager') DEFAULT 'customer',
                balance DECIMAL(10, 2) DEFAULT 0.00
            )
        """)
        
        # Check if columns exist, if not add them (simple migration)
        cursor.execute("SHOW COLUMNS FROM users LIKE 'role'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN role ENUM('customer', 'staff', 'manager') DEFAULT 'customer'")
            cursor.execute("ALTER TABLE users ADD COLUMN balance DECIMAL(10, 2) DEFAULT 0.00")

        # Books table update: Global catalog, price, stock, status
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                author VARCHAR(255) NOT NULL,
                publisher VARCHAR(255),
                summary TEXT,
                cover VARCHAR(255),
                isbn VARCHAR(20),
                year INT,
                type VARCHAR(50),
                price DECIMAL(10, 2) DEFAULT 0.00,
                stock INT DEFAULT 0,
                status ENUM('on_shelf', 'off_shelf') DEFAULT 'on_shelf'
            )
        """)
        
        # Migration for books
        cursor.execute("SHOW COLUMNS FROM books LIKE 'price'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE books ADD COLUMN price DECIMAL(10, 2) DEFAULT 0.00")
            cursor.execute("ALTER TABLE books ADD COLUMN stock INT DEFAULT 10")
            cursor.execute("ALTER TABLE books ADD COLUMN status ENUM('on_shelf', 'off_shelf') DEFAULT 'on_shelf'")
            # Remove user_id foreign key if exists or make it nullable/legacy?
            # For this requirement, books are global. We'll ignore user_id for now or set default.
            # If user_id exists and is NOT NULL, we might need to alter it.
            try:
                cursor.execute("ALTER TABLE books MODIFY user_id INT NULL")
            except:
                pass # user_id might not exist if created fresh above

        # Orders table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                total_price DECIMAL(10, 2) NOT NULL,
                status ENUM('pending', 'approved', 'shipped', 'completed', 'cancelled') DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Order Items table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                id INT AUTO_INCREMENT PRIMARY KEY,
                order_id INT NOT NULL,
                book_id INT NOT NULL,
                quantity INT NOT NULL,
                price_snapshot DECIMAL(10, 2) NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id),
                FOREIGN KEY (book_id) REFERENCES books(id)
            )
        """)

        # Create default Manager and Staff if not exist
        cursor.execute("SELECT id FROM users WHERE username='admin'")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO users (username, password, nickname, role, balance) VALUES (%s, %s, %s, %s, %s)",
                           ('admin', 'admin', '店长', 'manager', 0.00))
        else:
            # Ensure admin has manager role
            cursor.execute("UPDATE users SET role='manager' WHERE username='admin'")
        
        cursor.execute("SELECT id FROM users WHERE username='staff'")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO users (username, password, nickname, role, balance) VALUES (%s, %s, %s, %s, %s)",
                           ('staff', 'staff', '店员', 'staff', 0.00))
        else:
            cursor.execute("UPDATE users SET role='staff' WHERE username='staff'")

        cursor.execute("SET FOREIGN_KEY_CHECKS=1")
        conn.commit()
        return True
    except Error as error:
        print(f"Database init failed: {error}")
        return False
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

# Routes

@app.route('/')
def index():
    return send_from_directory('templates', 'store_index.html')

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

@app.route('/api/session', methods=['GET'])
def get_session():
    # Return current user info or guest status
    user_id = session.get('user_id')
    if user_id:
        # Fetch latest balance from database
        conn = connect_()
        if conn:
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT balance FROM users WHERE id=%s", (user_id,))
                db_user = cursor.fetchone()
                balance = float(db_user['balance']) if db_user else 0.00
                cursor.close()
            except:
                balance = float(session.get('balance', 0.00))
            finally:
                conn.close()
        else:
            balance = float(session.get('balance', 0.00))
    else:
        balance = 0.00
    
    user = {
        'id': user_id,
        'username': session.get('username'),
        'nickname': session.get('nickname'),
        'role': session.get('role', 'guest'),
        'balance': balance
    }
    return jsonify(user)

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    conn = connect_()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if user and user['password'] == password:
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['nickname'] = user['nickname']
        session['role'] = user['role']
        session['balance'] = float(user['balance'])
        return jsonify({'message': 'Login successful', 'role': user['role']})
    else:
        return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/logout')
def logout():
    session.clear()
    return jsonify({'message': 'Logged out'})

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    nickname = data.get('nickname')
    gender = data.get('gender', '其他')
    
    # New user gets random balance between 100 and 1000
    initial_balance = random.randint(100, 1000)

    conn = connect_()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, password, nickname, gender, role, balance) VALUES (%s, %s, %s, %s, 'customer', %s)",
                       (username, password, nickname, gender, initial_balance))
        conn.commit()
        return jsonify({'message': 'Registration successful', 'balance': initial_balance})
    except Error as e:
        return jsonify({'error': str(e)}), 400
    finally:
        conn.close()

# Product API
@app.route('/api/books', methods=['GET'])
def get_books():
    role = session.get('role', 'guest')
    page = int(request.args.get('page', 1))
    limit = 20
    offset = (page - 1) * limit
    
    search_type = request.args.get('searchType', 'all')
    keyword = request.args.get('keyword', '')

    conn = connect_()
    cursor = conn.cursor(dictionary=True)
    
    where_clauses = []
    params = []
    
    # Staff/Manager see all, Customers see only on_shelf
    if role not in ['staff', 'manager']:
        where_clauses.append("status = 'on_shelf'")
    
    if keyword:
        if search_type == 'all':
            where_clauses.append("(title LIKE %s OR author LIKE %s OR isbn LIKE %s)")
            like = f"%{keyword}%"
            params.extend([like, like, like])
        else:
            where_clauses.append(f"{search_type} LIKE %s")
            params.append(f"%{keyword}%")
            
    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    
    # Count total
    cursor.execute(f"SELECT COUNT(*) as total FROM books WHERE {where_sql}", params)
    total = cursor.fetchone()['total']
    
    # Fetch books
    cursor.execute(f"SELECT * FROM books WHERE {where_sql} ORDER BY id DESC LIMIT %s OFFSET %s", (*params, limit, offset))
    books = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return jsonify({
        'books': books,
        'total': total,
        'page': page,
        'pages': (total + limit - 1) // limit
    })

@app.route('/api/books', methods=['POST'])
def add_book():
    if session.get('role') not in ['staff', 'manager']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Handle file upload
    cover_filename = None
    if 'cover' in request.files:
        file = request.files['cover']
        if file and file.filename:
            try:
                filename = secure_filename(file.filename)
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                cover_filename = filename
            except Exception as e:
                return jsonify({'error': f'File upload failed: {str(e)}'}), 500
    
    data = request.form
    conn = connect_()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO books (title, author, publisher, isbn, year, type, price, stock, status, summary, cover)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            data['title'], data['author'], data.get('publisher'), data.get('isbn'), 
            data.get('year'), data.get('type'), data.get('price', 0), data.get('stock', 0),
            data.get('status', 'on_shelf'), data.get('summary'), cover_filename
        ))
        conn.commit()
        return jsonify({'message': 'Book added'})
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/books/<int:book_id>', methods=['PUT'])
def update_book(book_id):
    if session.get('role') not in ['staff', 'manager']:
        return jsonify({'error': 'Unauthorized'}), 403
        
    # Handle file upload
    cover_filename = None
    if 'cover' in request.files:
        file = request.files['cover']
        if file and file.filename:
            try:
                filename = secure_filename(file.filename)
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                cover_filename = filename
            except Exception as e:
                return jsonify({'error': f'File upload failed: {str(e)}'}), 500
    
    data = request.form
    conn = connect_()
    cursor = conn.cursor()
    try:
        update_fields = []
        params = []
        
        fields = ['title', 'author', 'price', 'stock', 'status', 'summary']
        for field in fields:
            if field in data:
                update_fields.append(f"{field}=%s")
                params.append(data[field])
        
        if cover_filename:
            update_fields.append("cover=%s")
            params.append(cover_filename)
        
        if update_fields:
            params.append(book_id)
            cursor.execute(f"""
                UPDATE books SET {', '.join(update_fields)}
                WHERE id=%s
            """, params)
        
        conn.commit()
        return jsonify({'message': 'Book updated'})
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# Cart API (Session Based)
@app.route('/api/cart', methods=['GET'])
def get_cart():
    cart = session.get('cart', {}) # {book_id: quantity}
    if not cart:
        return jsonify({'items': [], 'total': 0})
    
    book_ids = list(cart.keys())
    if not book_ids:
        return jsonify({'items': [], 'total': 0})
        
    conn = connect_()
    cursor = conn.cursor(dictionary=True)
    format_strings = ','.join(['%s'] * len(book_ids))
    cursor.execute(f"SELECT * FROM books WHERE id IN ({format_strings})", tuple(book_ids))
    books = cursor.fetchall()
    conn.close()
    
    items = []
    total = 0
    for book in books:
        qty = cart[str(book['id'])]
        item_total = float(book['price']) * qty
        total += item_total
        items.append({
            'book': book,
            'quantity': qty,
            'item_total': item_total
        })
        
    return jsonify({'items': items, 'total': total})

@app.route('/api/cart', methods=['POST'])
def add_to_cart():
    data = request.get_json()
    book_id = str(data.get('book_id'))
    quantity = int(data.get('quantity', 1))
    
    cart = session.get('cart', {})
    if book_id in cart:
        cart[book_id] += quantity
    else:
        cart[book_id] = quantity
    session['cart'] = cart
    return jsonify({'message': 'Added to cart', 'cart_count': sum(cart.values())})

@app.route('/api/cart/update', methods=['POST'])
def update_cart():
    data = request.get_json()
    book_id = str(data.get('book_id'))
    quantity = int(data.get('quantity', 0))
    
    cart = session.get('cart', {})
    if quantity <= 0:
        if book_id in cart:
            del cart[book_id]
    else:
        cart[book_id] = quantity
    session['cart'] = cart
    return jsonify({'message': 'Cart updated'})

@app.route('/api/cart/clear', methods=['POST'])
def clear_cart():
    session['cart'] = {}
    return jsonify({'message': 'Cart cleared'})

# Order API
@app.route('/api/orders', methods=['POST'])
def create_order():
    if 'user_id' not in session:
        return jsonify({'error': 'Please login to checkout'}), 401
    
    user_id = session['user_id']
    user_role = session.get('role', 'customer')
    cart = session.get('cart', {})
    if not cart:
        return jsonify({'error': 'Cart is empty'}), 400
        
    conn = connect_()
    cursor = conn.cursor(dictionary=True)
    
    try:
        conn.start_transaction()
        
        # 1. Calculate total and check stock
        total_price = 0
        order_items = []
        
        for book_id_str, qty in cart.items():
            book_id = int(book_id_str)
            cursor.execute("SELECT * FROM books WHERE id=%s FOR UPDATE", (book_id,))
            book = cursor.fetchone()
            
            if not book:
                raise Exception(f"Book ID {book_id} not found")
            if book['stock'] < qty:
                raise Exception(f"Insufficient stock for {book['title']}")
                
            price = float(book['price'])
            item_total = price * qty
            total_price += item_total
            order_items.append((book_id, qty, price))
            
            # Deduct stock
            cursor.execute("UPDATE books SET stock = stock - %s WHERE id = %s", (qty, book_id))
            
        # 2. Check User Balance (skip for staff/manager)
        if user_role not in ['staff', 'manager']:
            cursor.execute("SELECT balance FROM users WHERE id=%s FOR UPDATE", (user_id,))
            user = cursor.fetchone()
            if float(user['balance']) < total_price:
                raise Exception("Insufficient balance")
                
            # 3. Deduct Balance
            cursor.execute("UPDATE users SET balance = balance - %s WHERE id = %s", (total_price, user_id))
            session['balance'] = float(user['balance']) - total_price # Update session
        else:
            # For staff/manager, no balance check/deduct
            pass
        
        # 4. Create Order
        cursor.execute("INSERT INTO orders (user_id, total_price, status) VALUES (%s, %s, 'pending')", (user_id, total_price))
        order_id = cursor.lastrowid
        
        # 5. Create Order Items
        for item in order_items:
            cursor.execute("INSERT INTO order_items (order_id, book_id, quantity, price_snapshot) VALUES (%s, %s, %s, %s)",
                           (order_id, item[0], item[1], item[2]))
                           
        conn.commit()
        session['cart'] = {} # Clear cart
        return jsonify({'message': 'Order placed successfully', 'order_id': order_id})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/orders', methods=['GET'])
def get_orders():
    user_id = session.get('user_id')
    role = session.get('role', 'guest')
    
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
        
    conn = connect_()
    cursor = conn.cursor(dictionary=True)
    
    if role in ['staff', 'manager']:
        # Staff sees all orders, filter by status if needed
        status = request.args.get('status')
        if status:
            cursor.execute("SELECT orders.*, users.username FROM orders JOIN users ON orders.user_id = users.id WHERE status=%s ORDER BY created_at DESC", (status,))
        else:
            cursor.execute("SELECT orders.*, users.username FROM orders JOIN users ON orders.user_id = users.id ORDER BY created_at DESC")
    else:
        # Customer sees own orders
        cursor.execute("SELECT * FROM orders WHERE user_id=%s ORDER BY created_at DESC", (user_id,))
        
    orders = cursor.fetchall()
    
    # Enrich with items
    for order in orders:
        cursor.execute("""
            SELECT oi.*, b.title, b.cover 
            FROM order_items oi 
            JOIN books b ON oi.book_id = b.id 
            WHERE oi.order_id = %s
        """, (order['id'],))
        order['items'] = cursor.fetchall()
        
    conn.close()
    return jsonify(orders)

@app.route('/api/orders/<int:order_id>/audit', methods=['POST'])
def audit_order(order_id):
    user_id = session.get('user_id')
    role = session.get('role', 'guest')
    
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
        
    data = request.get_json()
    new_status = data.get('status') # 'approved', 'shipped', 'cancelled'
    
    print(f"Audit order {order_id} to {new_status} by user {user_id} role {role}")
    
    conn = None
    try:
        conn = connect_()
        if conn is None:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cursor = conn.cursor(dictionary=True)
        
        # Get order info
        cursor.execute("SELECT user_id, total_price, status FROM orders WHERE id=%s", (order_id,))
        order = cursor.fetchone()
        if not order:
            return jsonify({'error': 'Order not found'}), 404
        
        old_status = order['status']
        order_user_id = order['user_id']
        total_price = float(order['total_price'] or 0)
        
        # Allow customer to cancel their own orders, staff/manager to audit any
        if role not in ['staff', 'manager']:
            if order_user_id != user_id or new_status != 'cancelled':
                return jsonify({'error': 'Unauthorized'}), 403
        
        # If cancelling, check if allowed
        if new_status == 'cancelled':
            if old_status == 'shipped':
                return jsonify({'error': '已发货订单不能取消'}), 400
        
        # If cancelling, refund balance and restock
        if new_status == 'cancelled' and old_status != 'cancelled':
            # Check user role
            cursor.execute("SELECT role FROM users WHERE id=%s", (order_user_id,))
            user = cursor.fetchone()
            if user and user['role'] == 'customer':  # Only refund if customer paid
                cursor.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (total_price, order_user_id))
            
            # Restock items
            cursor.execute("SELECT book_id, quantity FROM order_items WHERE order_id=%s", (order_id,))
            items = cursor.fetchall()
            for item in items:
                cursor.execute("UPDATE books SET stock = stock + %s WHERE id = %s", (item['quantity'], item['book_id']))
        
        cursor.execute("UPDATE orders SET status=%s WHERE id=%s", (new_status, order_id))
        conn.commit()
        return jsonify({'message': f'Order status updated to {new_status}'})
    
    except Exception as e:
        print(f"Error in audit_order: {str(e)}")
        return jsonify({'error': f'Internal server error'}), 500
    finally:
        if conn:
            conn.close()

# Manager Stats
@app.route('/api/stats', methods=['GET'])
def get_stats():
    if session.get('role') != 'manager':
        return jsonify({'error': 'Unauthorized'}), 403
        
    conn = connect_()
    cursor = conn.cursor(dictionary=True)
    
    # Today's sales
    today = datetime.date.today()
    cursor.execute("SELECT COUNT(*) as count, SUM(total_price) as total FROM orders WHERE DATE(created_at) = %s AND status != 'cancelled'", (today,))
    daily_sales = cursor.fetchone()
    
    # Historical sales
    cursor.execute("SELECT COUNT(*) as count, SUM(total_price) as total FROM orders WHERE status != 'cancelled'")
    total_sales = cursor.fetchone()
    
    # Top selling books
    cursor.execute("""
        SELECT b.title, SUM(oi.quantity) as sold_count
        FROM order_items oi
        JOIN books b ON oi.book_id = b.id
        JOIN orders o ON oi.order_id = o.id
        WHERE o.status != 'cancelled'
        GROUP BY b.id
        ORDER BY sold_count DESC
        LIMIT 5
    """)
    top_books = cursor.fetchall()
    
    conn.close()
    return jsonify({
        'daily': daily_sales,
        'total': total_sales,
        'top_books': top_books
    })

if __name__ == '__main__':
    initialize_database()
    app.run(host='127.0.0.1', port=5002, debug=False, use_reloader=False)
