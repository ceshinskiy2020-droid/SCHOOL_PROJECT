from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from datetime import datetime, timezone, timedelta
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'ВАШ_УНИКАЛЬНЫЙ_СЕКРЕТНЫЙ_КЛЮЧ'  # Обязательно смените на уникальный ключ!

# UTC+3
UTC_PLUS_3 = timezone(timedelta(hours=3))

def init_db():
    """Инициализация базы данных — создание таблицы sessions, если её нет."""
    conn = sqlite3.connect('sessions.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            class TEXT NOT NULL,
            laptop_number TEXT,
            start_time TEXT NOT NULL,
            end_time TEXT
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("Инициализация БД завершена.")

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Получаем данные из формы
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        class_name = request.form.get('class', '').strip()

        # Валидация обязательных полей
        if not all([first_name, last_name, class_name]):
            flash('Пожалуйста, заполните имя, фамилию и класс.')
            return render_template('index.html')

        # Проверка на активную сессию
        conn = sqlite3.connect('sessions.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id FROM sessions 
            WHERE first_name = ? AND last_name = ? AND class = ? 
            AND end_time IS NULL
        ''', (first_name, last_name, class_name))
        active_session = cursor.fetchone()
        conn.close()

        if active_session:
            flash('У вас уже есть активная сессия. Завершите её прежде, чем начинать новую.')
            return render_template('index.html')

        # Создаём новую сессию
        start_time = datetime.now(UTC_PLUS_3).isoformat()
        conn = sqlite3.connect('sessions.db')
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO sessions (first_name, last_name, class, start_time)
                VALUES (?, ?, ?, ?)
            ''', (first_name, last_name, class_name, start_time))
            session_id = cursor.lastrowid
            conn.commit()
            logger.info(f"Создана сессия с ID: {session_id}")
        except sqlite3.Error as e:
            flash(f'Ошибка при создании сессии: {str(e)}')
            logger.error(f"Ошибка при INSERT в таблицу sessions: {e}")
            conn.close()
            return render_template('index.html')
        finally:
            conn.close()

        # Сохраняем ID сессии в сессию Flask
        session['session_id'] = session_id
        flash('Сессия начата! Теперь укажите номер ноутбука.')
        return redirect(url_for('start_session'))

    return render_template('index.html')


conn = sqlite3.connect('sessions.db')
cursor = conn.cursor()
try:
    cursor.execute('INSERT INTO sessions ...')
    conn.commit()
except sqlite3.Error as e:
    print(f"Ошибка: {e}")
finally:
    conn.close()


@app.route('/start_session', methods=['GET', 'POST'])
def start_session():
    if 'session_id' not in session:
        flash('Нет активной сессии. Начните новую.')
        return redirect(url_for('index'))

    if request.method == 'POST':
        laptop_number = request.form.get('laptop_number', '').strip()

        if not laptop_number:
            flash('Введите номер ноутбука.')
            return render_template('start_session.html')

        # Обновляем сессию — добавляем номер ноутбука
        conn = sqlite3.connect('sessions.db')
        cursor = conn.cursor()
        try:
            cursor.execute('''
                UPDATE sessions SET laptop_number = ? WHERE id = ?
            ''', (laptop_number, session['session_id']))
            conn.commit()
            logger.info(f"Обновлена сессия {session['session_id']} — добавлен номер ноутбука.")
            flash('Номер ноутбука сохранён. Сессия активна.')
        except sqlite3.Error as e:
            flash(f'Ошибка при обновлении сессии: {str(e)}')
            logger.error(f"Ошибка при UPDATE сессии {session['session_id']}: {e}")
        finally:
            conn.close()

        return redirect(url_for('finish'))

    return render_template('start_session.html')

@app.route('/finish')
def finish():
    if 'session_id' not in session:
        flash('Нет активной сессии. Начните новую.')
        return redirect(url_for('index'))

    # Получаем данные сессии из БД
    conn = sqlite3.connect('sessions.db')
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM sessions WHERE id = ?', (session['session_id'],))
        session_data = cursor.fetchone()
        if not session_data:
            flash('Сессия не найдена в базе данных.')
            logger.warning(f"Сессия с ID {session['session_id']} не найдена в БД.")
            session.pop('session_id', None)
            return redirect(url_for('index'))
    except sqlite3.Error as e:
        flash(f'Ошибка при получении данных сессии: {str(e)}')
        logger.error(f"Ошибка при SELECT сессии {session['session_id']}: {e}")
        session.pop('session_id', None)
        return redirect(url_for('index'))
    finally:
        conn.close()

    return render_template('finish.html', session_data=session_data)

@app.route('/end_session', methods=['POST'])
def end_session():
    if 'session_id' not in session:
        flash('Нет активной сессии.')
        return redirect(url_for('index'))

    end_time = datetime.now(UTC_PLUS_3).isoformat()
    conn = sqlite3.connect('sessions.db')
    cursor = conn.cursor()
    try:
        cursor.execute('''
            UPDATE sessions SET end_time = ? WHERE id = ?
        ''', (end_time, session['session_id']))
        conn.commit()
        logger.info(f"Сессия {session['session_id']} завершена в {end_time}")
        flash('Сессия завершена!')
    except sqlite3.Error as e:
        flash(f'Ошибка при завершении сессии: {str(e)}')
        logger.error(f"Ошибка при UPDATE end_time для сессии {session['session_id']}: {e}")
    finally:
        conn.close()
        session.pop('session_id', None)

    return redirect(url_for('index'))

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('session_id', None)
    flash('Вы вышли из системы.')
    logger.info("Пользователь вышел из системы.")
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()  # Инициализируем БД при запуске
    app.run(debug=True)
