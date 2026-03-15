from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from datetime import datetime, timezone, timedelta
import logging
import hashlib
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'ВАШ_УНИКАЛЬНЫЙ_СЕКРЕТНЫЙ_КЛЮЧ_ИЗМЕНИТЕ_ЭТО'

# UTC+3
UTC_PLUS_3 = timezone(timedelta(hours=3))


def init_db():
    """Инициализация и обновление базы данных."""
    conn = sqlite3.connect('sessions.db')
    cursor = conn.cursor()

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

    # Таблица сессий - создаем без feedback и rating
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        button_number TEXT,
        start_time TEXT NOT NULL,
        end_time TEXT,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    ''')

    try:
        cursor.execute('SELECT feedback FROM sessions LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute('ALTER TABLE sessions ADD COLUMN feedback TEXT')
        logger.info("Добавлена колонка feedback в таблицу sessions")

    try:
        cursor.execute('SELECT rating FROM sessions LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute('ALTER TABLE sessions ADD COLUMN rating INTEGER')
        logger.info("Добавлена колонка rating в таблицу sessions")

    conn.commit()
    conn.close()
    logger.info("Инициализация БД завершена.")


def hash_password(password):
    """Хеширование пароля."""
    return hashlib.sha256(password.encode()).hexdigest()


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

    start_time = datetime.now(UTC_PLUS_3).isoformat()
    try:
        cursor.execute('''
        INSERT INTO sessions (user_id, button_number, start_time)
        VALUES (?, ?, ?)
        ''', (session['user_id'], button_number, start_time))
        session_id = cursor.lastrowid
        conn.commit()

        session['session_id'] = session_id
        session['button_number'] = button_number

        logger.info(f"Начата сессия {session_id} с кнопкой {button_number}")
        flash('Сессия успешно начата!')

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

    # ИСПРАВЛЕНО: Правильная обработка времени
    start_str = current_session_data[2]
    try:
        # Пробуем разные форматы ISO
        if 'Z' in start_str:
            start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        elif '+' in start_str:
            start_dt = datetime.fromisoformat(start_str)
        else:
            # Если нет timezone info, считаем локальным UTC+3
            start_dt = datetime.fromisoformat(start_str)
            start_dt = start_dt.replace(tzinfo=UTC_PLUS_3)
        formatted_start = start_dt.strftime('%d.%m.%Y %H:%M')
    except (ValueError, TypeError):
        # Fallback для поврежденных данных
        formatted_start = start_str[:16] if start_str else 'Неизвестно'

    session_data = {
        'id': current_session_data[0],
        'button_number': current_session_data[1],
        'start_time': formatted_start,  # Теперь всегда корректная строка
        'first_name': current_session_data[3],
        'last_name': current_session_data[4],
        'class': current_session_data[5]
    }

    return render_template('current_session.html', session_data=session_data)


@app.route('/end_session', methods=['GET', 'POST'])
def end_session():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    end_time = datetime.now(UTC_PLUS_3).isoformat()
    conn = sqlite3.connect('sessions.db')
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT id FROM sessions 
            WHERE user_id = ? AND end_time IS NULL
        ''', (session['user_id'],))
        active_session = cursor.fetchone()

        if active_session:
            cursor.execute('''
                UPDATE sessions SET end_time = ? 
                WHERE id = ?
            ''', (end_time, active_session[0]))
            conn.commit()
            logger.info(f"Сессия {active_session[0]} пользователя {session['user_id']} завершена")
            flash('Сессия завершена!')
        else:
            flash('Активная сессия не найдена.')
            conn.close()
            return redirect(url_for('select_button'))

    except sqlite3.Error as e:
        flash(f'Ошибка при завершении сессии: {str(e)}')
        logger.error(f"Ошибка при завершении сессии: {e}")
    finally:
        conn.close()

    session.pop('session_id', None)
    session.pop('button_number', None)

    return redirect(url_for('feedback'))


@app.route('/feedback', methods=['GET', 'POST'])
def feedback():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        rating = request.form.get('rating')
        feedback_text = request.form.get('feedback', '').strip()

        if not rating or not rating.isdigit() or not (1 <= int(rating) <= 5):
            flash('Пожалуйста, оцените сеанс от 1 до 5 звёзд.')
            return redirect(url_for('feedback'))

        rating = int(rating)

        conn = sqlite3.connect('sessions.db')
        cursor = conn.cursor()

        try:
            cursor.execute('''
                UPDATE sessions
                SET feedback = ?, rating = ?
                WHERE user_id = ? AND end_time IS NOT NULL
                ORDER BY start_time DESC
                LIMIT 1
            ''', (feedback_text, rating, session['user_id']))

            if cursor.rowcount > 0:
                conn.commit()
                logger.info(f"Отзыв сохранён для пользователя {session['user_id']}: рейтинг={rating}")
                flash('Спасибо за ваш отзыв!')
            else:
                flash('Сессия для отзыва не найдена.')

            return redirect(url_for('history'))

        except sqlite3.Error as e:
            flash(f'Ошибка при сохранении отзыва: {str(e)}')
            logger.error(f"Ошибка при сохранении отзыва: {e}")
        finally:
            conn.close()

        return redirect(url_for('current_session'))

    return render_template('feedback.html')  # Используем feedback.html


@app.route('/history')
def history():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect('sessions.db')
    cursor = conn.cursor()

    # Всегда запрашиваем с COALESCE для безопасности
    cursor.execute('''
        SELECT button_number, 
               start_time, 
               end_time, 
               COALESCE(feedback, '') as feedback,
               COALESCE(rating, 0) as rating
        FROM sessions 
        WHERE user_id = ? 
        ORDER BY start_time DESC
        LIMIT 20
    ''', (session['user_id'],))

    sessions = cursor.fetchall()
    conn.close()

    sessions_processed = []
    for sess in sessions:
        # Гарантированно 5 элементов
        button = sess[0] or ''
        start_str = sess[1] or ''
        end_str = sess[2] or ''
        feedback_text = sess[3] or ''
        rating = sess[4] or 0

        # Обработка времени начала
        if start_str:
            try:
                if 'Z' in start_str:
                    start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                elif '+' in start_str:
                    start_dt = datetime.fromisoformat(start_str)
                else:
                    start_dt = datetime.fromisoformat(start_str)
                    start_dt = start_dt.replace(tzinfo=UTC_PLUS_3)
                start_formatted = start_dt.strftime('%d.%m.%Y %H:%M')
            except (ValueError, TypeError):
                start_formatted = start_str[:16]
        else:
            start_formatted = 'Неизвестно'

        # Обработка времени окончания и длительности
        duration = None
        if end_str:
            try:
                if 'Z' in end_str:
                    end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                elif '+' in end_str:
                    end_dt = datetime.fromisoformat(end_str)
                else:
                    end_dt = datetime.fromisoformat(end_str)
                    end_dt = end_dt.replace(tzinfo=UTC_PLUS_3)
                end_formatted = end_dt.strftime('%d.%m.%Y %H:%M')

                # Вычисляем длительность только если есть start_time
                if start_str:
                    if 'Z' in start_str:
                        start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                    else:
                        start_dt = datetime.fromisoformat(start_str)
                        start_dt = start_dt.replace(tzinfo=UTC_PLUS_3)
                    duration_minutes = int((end_dt - start_dt).total_seconds() / 60)
                    duration = f"{duration_minutes} мин"
            except (ValueError, TypeError):
                end_formatted = end_str[:16]
                duration = None
        else:
            end_formatted = 'В процессе'
            duration = None

        # ИСПРАВЛЕНО: rating всегда строка для шаблона
        rating_display = str(rating) if rating and rating > 0 else 'Не оценено'
        feedback_display = feedback_text if feedback_text.strip() else 'Нет отзыва'

        sessions_processed.append({
            'button': button,
            'start': start_formatted,
            'end': end_formatted,
            'duration': duration or 'Неизвестно',
            'feedback': feedback_display,
            'rating': rating_display
        })

    return render_template('history.html', sessions=sessions_processed)

@app.route('/admin')
def admin():
    # Простая проверка на админа (можно расширить)
    if 'user_id' not in session or session.get('username') != 'admin':
        flash('Доступ запрещен.')
        return redirect(url_for('select_button'))

    conn = sqlite3.connect('sessions.db')
    cursor = conn.cursor()

    # Общая статистика
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM sessions')
    total_sessions = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM sessions WHERE end_time IS NULL')
    active_sessions = cursor.fetchone()[0]

    # Проверяем наличие колонки rating
    cursor.execute("PRAGMA table_info(sessions)")
    columns = [column[1] for column in cursor.fetchall()]

    if 'rating' in columns:
        cursor.execute('SELECT AVG(rating) FROM sessions WHERE rating IS NOT NULL')
        avg_rating = cursor.fetchone()[0]
        if avg_rating:
            avg_rating = round(avg_rating, 1)
        else:
            avg_rating = 0
    else:
        avg_rating = 0

    conn.close()

    stats = {
        'total_users': total_users,
        'total_sessions': total_sessions,
        'active_sessions': active_sessions,
        'avg_rating': avg_rating
    }

    return render_template('admin.html', stats=stats)


if __name__ == '__main__':
    init_db()

    print("=" * 50)
    print("СИСТЕМА УЧЕТА УЧЕБНЫХ СЕССИЙ")
    print("=" * 50)
    print("Сервер запущен: http://localhost:5000")
    print("Для входа: http://localhost:5000/login")
    print("Для регистрации: http://localhost:5000/register")
    print("=" * 50)
    app.run(debug=True, port=5000)
