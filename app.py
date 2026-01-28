from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from datetime import datetime, timezone, timedelta
import logging
import hashlib
import os

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'ВАШ_УНИКАЛЬНЫЙ_СЕКРЕТНЫЙ_КЛЮЧ'

# UTC+3
UTC_PLUS_3 = timezone(timedelta(hours=3))


def init_db():
    """Инициализация базы данных."""
    conn = sqlite3.connect('sessions.db')
    cursor = conn.cursor()

    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        class TEXT NOT NULL
    )
    ''')

    # Таблица сессий
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        button_number TEXT,
        start_time TEXT NOT NULL,
        end_time TEXT
    )
    ''')

    conn.commit()
    conn.close()
    logger.info("Инициализация БД завершена.")


def hash_password(password):
    """Хеширование пароля."""
    return hashlib.sha256(password.encode()).hexdigest()


# Контекстный процессор для добавления текущего года во все шаблоны
@app.context_processor
def inject_current_year():
    return {'current_year': datetime.now().year}


# ========== РЕГИСТРАЦИЯ И ВХОД ==========
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        class_name = request.form.get('class', '').strip()

        if not all([username, password, first_name, last_name, class_name]):
            flash('Все поля обязательны для заполнения.')
            return render_template('register.html')

        hashed_password = hash_password(password)

        conn = sqlite3.connect('sessions.db')
        cursor = conn.cursor()
        try:
            cursor.execute('''
            INSERT INTO users (username, password, first_name, last_name, class)
            VALUES (?, ?, ?, ?, ?)
            ''', (username, hashed_password, first_name, last_name, class_name))
            conn.commit()
            user_id = cursor.lastrowid

            # Автоматический вход после регистрации
            session['user_id'] = user_id
            session['username'] = username
            session['first_name'] = first_name
            session['last_name'] = last_name
            session['class'] = class_name

            logger.info(f"Зарегистрирован новый пользователь: {username}")
            flash('Регистрация успешна!')
            return redirect(url_for('select_button'))

        except sqlite3.IntegrityError:
            flash('Пользователь с таким логином уже существует.')
        except sqlite3.Error as e:
            flash(f'Ошибка при регистрации: {str(e)}')
            logger.error(f"Ошибка при регистрации: {e}")
        finally:
            conn.close()

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not all([username, password]):
            flash('Введите логин и пароль.')
            return render_template('login.html')

        hashed_password = hash_password(password)

        conn = sqlite3.connect('sessions.db')
        cursor = conn.cursor()
        cursor.execute('SELECT id, first_name, last_name, class FROM users WHERE username = ? AND password = ?',
                       (username, hashed_password))
        user = cursor.fetchone()
        conn.close()

        if user:
            session['user_id'] = user[0]
            session['username'] = username
            session['first_name'] = user[1]
            session['last_name'] = user[2]
            session['class'] = user[3]
            flash('Вход выполнен успешно!')
            return redirect(url_for('select_button'))
        else:
            flash('Неверный логин или пароль.')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы.')
    return redirect(url_for('login'))


# ========== ОСНОВНЫЕ СТРАНИЦЫ ==========
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('select_button'))


@app.route('/select_button')
def select_button():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Проверяем, есть ли активная сессия
    conn = sqlite3.connect('sessions.db')
    cursor = conn.cursor()
    cursor.execute('''
    SELECT id FROM sessions 
    WHERE user_id = ? AND end_time IS NULL
    ''', (session['user_id'],))
    active_session = cursor.fetchone()
    conn.close()

    if active_session:
        return redirect(url_for('current_session'))

    return render_template('select_button.html')


@app.route('/start_session/<button_number>')
def start_session(button_number):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Проверяем, нет ли уже активной сессии
    conn = sqlite3.connect('sessions.db')
    cursor = conn.cursor()
    cursor.execute('''
    SELECT id FROM sessions 
    WHERE user_id = ? AND end_time IS NULL
    ''', (session['user_id'],))
    active_session = cursor.fetchone()

    if active_session:
        conn.close()
        flash('У вас уже есть активная сессия.')
        return redirect(url_for('current_session'))

    # Создаем новую сессию
    start_time = datetime.now(UTC_PLUS_3).isoformat()
    try:
        cursor.execute('''
        INSERT INTO sessions (user_id, button_number, start_time)
        VALUES (?, ?, ?)
        ''', (session['user_id'], button_number, start_time))
        session_id = cursor.lastrowid
        conn.commit()

        # Сохраняем ID сессии в сессии Flask
        session['session_id'] = session_id
        session['button_number'] = button_number

        logger.info(f"Начата сессия {session_id} с кнопкой {button_number}")

    except sqlite3.Error as e:
        flash(f'Ошибка при создании сессии: {str(e)}')
        logger.error(f"Ошибка при создании сессии: {e}")
        conn.close()
        return redirect(url_for('select_button'))

    conn.close()
    return redirect(url_for('current_session'))


@app.route('/current_session')
def current_session():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect('sessions.db')
    cursor = conn.cursor()
    cursor.execute('''
    SELECT s.id, s.button_number, s.start_time, u.first_name, u.last_name, u.class
    FROM sessions s
    JOIN users u ON s.user_id = u.id
    WHERE s.user_id = ? AND s.end_time IS NULL
    ORDER BY s.start_time DESC
    LIMIT 1
    ''', (session['user_id'],))

    current_session_data = cursor.fetchone()
    conn.close()

    if not current_session_data:
        return redirect(url_for('select_button'))

    return render_template('current_session.html', session_data=current_session_data)


@app.route('/end_session', methods=['GET', 'POST'])
def end_session():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    end_time = datetime.now(UTC_PLUS_3).isoformat()
    conn = sqlite3.connect('sessions.db')
    cursor = conn.cursor()

    try:
        cursor.execute('''
        UPDATE sessions SET end_time = ? 
        WHERE user_id = ? AND end_time IS NULL
        ''', (end_time, session['user_id']))
        conn.commit()

        # Очищаем данные сессии
        if 'session_id' in session:
            session.pop('session_id')
        if 'button_number' in session:
            session.pop('button_number')

        logger.info(f"Сессия пользователя {session['user_id']} завершена")
        flash('Сессия завершена.')

    except sqlite3.Error as e:
        flash(f'Ошибка при завершении сессии: {str(e)}')
        logger.error(f"Ошибка при завершении сессии: {e}")
    finally:
        conn.close()

    return redirect(url_for('select_button'))


@app.route('/history')
def history():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect('sessions.db')
    cursor = conn.cursor()
    cursor.execute('''
    SELECT button_number, start_time, end_time 
    FROM sessions 
    WHERE user_id = ? 
    ORDER BY start_time DESC
    LIMIT 20
    ''', (session['user_id'],))

    sessions_history = cursor.fetchall()
    conn.close()

    # Форматируем даты
    sessions_processed = []
    for sess in sessions_history:
        start_str = sess[1]
        end_str = sess[2]

        if start_str:
            try:
                start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                start_formatted = start_dt.strftime('%d.%m.%Y %H:%M')
            except:
                start_formatted = start_str[:16]
        else:
            start_formatted = ''

        if end_str:
            try:
                end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                end_formatted = end_dt.strftime('%d.%m.%Y %H:%M')
                duration = (end_dt - start_dt).seconds // 60
            except:
                end_formatted = end_str[:16]
                duration = None
        else:
            end_formatted = None
            duration = None

        sessions_processed.append((sess[0], start_formatted, end_formatted, duration))

    return render_template('history.html', sessions=sessions_processed)


if __name__ == '__main__':
    # Удаляем старую базу данных при первом запуске
    if os.path.exists('sessions.db'):
        os.remove('sessions.db')
        print("Старая база данных удалена. Создаем новую...")

    init_db()
    print("=" * 50)
    print("СИСТЕМА УЧЕТА УЧЕБНЫХ СЕССИЙ")
    print("=" * 50)
    print("Сервер запущен: http://localhost:5000")
    print("Для входа: http://localhost:5000/login")
    print("Для регистрации: http://localhost:5000/register")
    print("=" * 50)
    app.run(debug=True, port=5000)

