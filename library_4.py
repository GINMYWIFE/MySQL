'''index: 图书管理系统主程序
   login: 登录页
   register: 注册页'''

from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import mysql.connector as mc
from mysql.connector import Error
from werkzeug.utils import secure_filename
import os

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = 'your_secret_key'
UPLOAD_FOLDER = 'static/covers'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

database_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '994694',
    'database': 'library',
    'connection_timeout': 5
}

# 连接数据库
def connect_():
    try:
        conn = mc.connect(**database_config)
        return conn
    except Error as e:
        print(f"数据库连接失败: {e}")
        return None

def initialize_database():
    conn = connect_()
    if conn is None:
        return False
    try:
        cursor = conn.cursor()
        # 增加 users 表 与 books 表外键
        #密码明文存储，待后续修改
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,   
                nickname VARCHAR(100),
                gender ENUM('男', '女', '其他') DEFAULT '其他'
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                title VARCHAR(255) NOT NULL,
                author VARCHAR(255) NOT NULL,
                publisher VARCHAR(255),
                summary TEXT,
                cover VARCHAR(255),  #封面路径
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        # 设置初始默认管理员账号，首次登录时使用
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        if user_count == 0:
            cursor.execute(
                """
                INSERT INTO users (username, password, nickname, gender)
                VALUES (%s, %s, %s, %s)
                """,
                ("admin", "admin", "管理员", "其他")
            )
        # 读取管理员 id，旧表迁移
        try:
            cursor.execute("SELECT id FROM users WHERE username=%s ORDER BY id LIMIT 1", ("admin",))
            row = cursor.fetchone()
            admin_id = row[0] if row else 1
        except Exception:
            admin_id = 1
        conn.commit()
        return True
        
    except Error as error:
        print(f"数据库初始化失败: {error}")
        return False
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

@app.route('/')
def index():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    # 用户登录逻辑
    username = request.form.get('username', '')
    password = request.form.get('password', '')

    app.logger.info(f"登录尝试：username={username}")
    conn = connect_()
    if conn is None:
        app.logger.error("数据库连接失败")
        return redirect(url_for('index', error='数据库连接失败，请检查MySQL服务'))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, password, nickname, gender FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and user[1] == password:
            session['user_id'] = user[0]
            session['username'] = username
            session['nickname'] = user[2]
            session['gender'] = user[3]
            app.logger.info("登录成功，跳转到 /books")
            return redirect(url_for('books_page'))
        else:
            app.logger.warning("用户名或密码错误")
            # 登录失败时附带错误提示参数，前端可视化显示
            return redirect(url_for('index', error='用户名或密码错误'))
    except Exception as e:
        app.logger.exception(e)
        return redirect(url_for('index', error='登录过程中发生错误，请重试'))

@app.route('/logout')
def logout():
    # 退出登录
    session.clear()
    return redirect(url_for('index'))

@app.route('/user/update', methods=['POST'])
def update_user():
    # 修改昵称、性别、密码
    user_id = session.get('user_id')
    nickname = request.form.get('nickname')
    gender = request.form.get('gender')
    password = request.form.get('password')

    # 如果密码为空则不更新密码
    conn = connect_()
    cursor = conn.cursor()
    if password:  # 如果提供了新密码
        cursor.execute("""
            UPDATE users SET nickname=%s, gender=%s, password=%s WHERE id=%s
        """, (nickname, gender, password, user_id))
    else:  # 否则只更新昵称和性别
        cursor.execute("""
            UPDATE users SET nickname=%s, gender=%s WHERE id=%s
        """, (nickname, gender, user_id))
    conn.commit()
    cursor.close()
    conn.close()

    session['nickname'] = nickname
    session['gender'] = gender
    return jsonify({'message': '用户信息更新成功'})

@app.route('/books')
def books_page():
    # 主书籍页面
    if 'user_id' not in session:
        return redirect(url_for('index'))
    # index.html 作为界面
    return render_template('index.html', username=session.get('username', ''), nickname=session.get('nickname', ''), gender=session.get('gender', ''))

# 【新增】上传封面文件
@app.route('/upload_cover', methods=['POST'])
def upload_cover():
    if 'file' not in request.files:
        return jsonify({'error': '未找到文件'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '未选择文件'}), 400
    if file:
        import uuid
        ext = os.path.splitext(file.filename)[1]
        filename = str(uuid.uuid4()) + ext
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        # 返回相对路径供前端访问
        return jsonify({'url': f'/static/covers/{filename}'})
    return jsonify({'error': '上传失败'}), 500

# API：书籍列表（分页+搜索）
@app.route('/api/books', methods=['GET'])
def get_books():
    if 'user_id' not in session:
        return jsonify({'error': '未登录'}), 401

    page = int(request.args.get('page', 1))
    keyword = request.args.get('keyword', '')
    limit = 20
    offset = (page - 1) * limit

    conn = connect_()
    if conn is None:
        return jsonify({'error': '数据库连接失败'}), 500
    try:
        cursor = conn.cursor()
        # 计算总记录数（扩展为包含 isbn/type/year 的模糊匹配）
        count_query = """
            SELECT COUNT(*) FROM books 
            WHERE user_id=%s AND (
                title LIKE %s OR author LIKE %s OR isbn LIKE %s OR type LIKE %s OR CAST(year AS CHAR) LIKE %s
            )
        """
        like = f"%{keyword}%"
        cursor.execute(count_query, (session['user_id'], like, like, like, like, like))
        total = cursor.fetchone()[0]

        # 查询当前页数据
        query = """
            SELECT id, user_id, title, author, isbn, year, type, cover FROM books 
            WHERE user_id=%s AND (
                title LIKE %s OR author LIKE %s OR isbn LIKE %s OR type LIKE %s OR CAST(year AS CHAR) LIKE %s
            )
            ORDER BY id DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(query, (session['user_id'], like, like, like, like, like, limit, offset))
        books = cursor.fetchall()

        book_list = []
        for b in books:
            book_list.append({
                'id': b[0],
                'title': b[2],
                'author': b[3],
                'isbn': b[4] or '',
                'year': (int(b[5]) if b[5] not in (None, '') else ''),
                'type': b[6] or '',
                'cover': b[7] or ''
            })
        return jsonify(book_list)
    except Exception:
        # 旧库结构缺失时降级返回基础字段，避免 500
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, author FROM books LIMIT %s OFFSET %s", (limit, offset))
            books = cursor.fetchall()
            book_list = []
            for b in books:
                book_list.append({
                    'id': b[0],
                    'title': b[1],
                    'author': b[2],
                    'isbn': '',
                    'year': '',
                    'type': ''
                })
            return jsonify(book_list)
        except Exception as e2:
            app.logger.exception(e2)
            return jsonify({'error': '查询失败'}), 500
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

# API：添加书籍
@app.route('/api/books', methods=['POST'])
def add_book():
    # 统一返回 JSON，避免前端解析失败
    if 'user_id' not in session:
        return jsonify({'error': '未登录'}), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': '请求体必须为 JSON'}), 400

    title = data.get('title', '').strip()
    author = data.get('author', '').strip()
    isbn = (data.get('isbn') or '').strip()
    year = data.get('year')
    book_type = (data.get('type') or '').strip()
    publisher = (data.get('publisher') or '').strip()
    summary = (data.get('summary') or '').strip()
    cover = (data.get('cover') or '').strip()

    if not title or not author:
        return jsonify({'error': '书名和作者为必填项'}), 400

    # YEAR字段处理：允许空，若提供则尝试转换为整数
    if year in ("", None):
        year_val = None
    else:
        try:
            year_val = int(year)
        except Exception:
            return jsonify({'error': '年份必须为数字'}), 400

    conn = connect_()
    if conn is None:
        return jsonify({'error': '数据库连接失败'}), 500

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO books (title, author, isbn, year, `type`, publisher, summary, cover, user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                title,
                author,
                isbn,
                year_val,
                book_type,
                publisher,
                summary,
                cover,
                session['user_id']
            )
        )
        conn.commit()
        return jsonify({'message': '添加成功'})
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        app.logger.exception(e)
        return jsonify({'error': f'添加失败：{str(e)}'}), 500
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


# API：修改书籍
@app.route('/api/books/<int:book_id>', methods=['PUT'])
def update_book(book_id):
    if 'user_id' not in session:
        return jsonify({'error': '未登录'}), 401

    data = request.get_json()
    conn = connect_()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE books SET title=%s, author=%s, isbn=%s, year=%s, `type`=%s, publisher=%s, summary=%s, cover=%s
        WHERE id=%s AND user_id=%s
    """, (
        data['title'],
        data['author'],
        data.get('isbn', ''),
        data.get('year', None),
        data.get('type', ''),
        data.get('publisher', ''),
        data.get('summary', ''),
        data.get('cover', ''),
        book_id,
        session['user_id']
    ))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'message': '更新成功'})

# API：删除书籍
@app.route('/api/books/<int:book_id>', methods=['DELETE'])
def delete_book(book_id):
    if 'user_id' not in session:
        return jsonify({'error': '未登录'}), 401

    conn = connect_()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM books WHERE id=%s AND user_id=%s", (book_id, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'message': '删除成功'})

# API：获取单本书籍详情
@app.route('/api/books/<int:book_id>', methods=['GET'])
def get_book(book_id):
    if 'user_id' not in session:
        return jsonify({'error': '未登录'}), 401
    conn = connect_()
    if conn is None:
        return jsonify({'error': '数据库连接失败'}), 500
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, user_id, title, author, isbn, year, type FROM books WHERE id=%s AND user_id=%s",
            (book_id, session['user_id'])
        )
        b = cursor.fetchone()
        if not b:
            return jsonify({'error': '未找到'}), 404
        return jsonify({
            'id': b[0], 'title': b[2], 'author': b[3],
            'isbn': b[4] or '', 'year': (int(b[5]) if b[5] not in (None, '') else ''), 'type': b[6] or ''
        })
    except Exception as e:
        app.logger.exception(e)
        return jsonify({'error': '查询失败'}), 500
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

# 搜索书籍
@app.route('/api/books/search', methods=['GET'])
def search_books():
    if 'user_id' not in session:
        return jsonify({'error': '未登录'}), 401
    search_type = request.args.get('type', '').strip()
    value = request.args.get('value', '').strip()
    conn = connect_()
    if conn is None:
        return jsonify({'error': '数据库连接失败'}), 500
    try:
        cursor = conn.cursor()
        where = ["user_id=%s"]
        params = [session['user_id']]
        # 支持 id 精确匹配
        if search_type == 'id' and value.isdigit():
            where.append("id=%s")
            params.append(int(value))
        elif search_type in ('title', 'author', 'isbn', 'type') and value:
            where.append(f"{search_type} LIKE %s")
            params.append(f"%{value}%")
        elif search_type == 'year' and value:
            if value.isdigit():
                where.append("year=%s")
                params.append(int(value))
            else:
                where.append("CAST(year AS CHAR) LIKE %s")
                params.append(f"%{value}%")
        else:
            # 在 title/author/isbn/type/year 中模糊搜索
            if value:
                like = f"%{value}%"
                where.append("(title LIKE %s OR author LIKE %s OR isbn LIKE %s OR type LIKE %s OR CAST(year AS CHAR) LIKE %s)")
                params.extend([like, like, like, like, like])
        query = f"SELECT id, user_id, title, author, isbn, year, type FROM books WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT 100"
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        books = [{
            'id': r[0], 'title': r[2], 'author': r[3],
            'isbn': r[4] or '', 'year': (int(r[5]) if r[5] not in (None, '') else ''), 'type': r[6] or ''
        } for r in rows]
        # 返回对象，兼容前端对 result.books / result.count / result.search_type 的读取
        allowed_types = {'all', 'id', 'title', 'author', 'isbn', 'year', 'type'}
        resp = {
            'books': books,
            'count': len(books),
            'search_type': (search_type if search_type in allowed_types else 'all'),
            'search_value': value
        }
        return jsonify(resp)
    except Exception as e:
        app.logger.exception(e)
        return jsonify({'error': '搜索失败'}), 500
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

# 注册功能：GET 显示注册页，POST 提交注册
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    nickname = request.form.get('nickname', '').strip()
    gender = request.form.get('gender', '其他')
    if not username or not password:
        return redirect(url_for('register') + '?error=用户名和密码为必填')
    if gender not in ('男', '女', '其他'):
        gender = '其他'
    conn = connect_()
    if conn is None:
        return redirect(url_for('register') + '?error=数据库连接失败')
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username=%s", (username,))
        exists = cursor.fetchone()
        if exists:
            cursor.close(); conn.close()
            return redirect(url_for('register') + '?error=用户名已存在')
        cursor.execute(
            "INSERT INTO users (username, password, nickname, gender) VALUES (%s, %s, %s, %s)",
            (username, password, nickname or username, gender)
        )
        conn.commit()
        cursor.close(); conn.close()
        return redirect(url_for('index') + '?success=注册成功，请登录')
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        app.logger.exception(e)
        return redirect(url_for('register') + '?error=注册失败，请重试')

# 增加健康检查与错误处理，避免后端异常导致白屏
@app.route('/healthz')
def healthz():
    return 'ok', 200

@app.errorhandler(404)
def not_found(e):
    return '页面不存在（404）。', 404

@app.errorhandler(500)
def internal_error(e):
    # 打印异常日志并返回可视的错误提示
    try:
        app.logger.exception(e)
    finally:
        return '服务器内部错误（500），请查看终端日志。', 500

# 启动应用
if __name__ == '__main__':
    try:
        initialize_database()
        print("数据库初始化完成")
        # 关闭调试重载器，绑定到本地回环地址，避免权限/防火墙导致白屏
        app.run(host='127.0.0.1', port=5001, debug=False, use_reloader=False, threaded=True)
    except OSError as e:
        print(f"端口 5001 启动失败: {e}")
        for alt_port in [8000, 8080, 3000, 6000, 9000]:
            try:
                print(f"尝试备用端口 {alt_port} ...")
                app.run(host='127.0.0.1', port=alt_port, debug=False, use_reloader=False, threaded=True)
                break
            except OSError as e2:
                print(f"端口 {alt_port} 启动失败: {e2}")
        else:
            print("服务器启动失败")
    except Exception as e:
        print(f"启动失败: {e}")



