import sqlite3
import urllib.request
import json
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

# ------------------------------------------------------------------
PUSH_CHANNEL_ID = "mirror_admin_push_77"
WEBVIEW_URL = "https://yalica.github.io/SaaS/owner.html" 
# ------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def init_db():
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    
    # 1. Таблица отзывов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id TEXT DEFAULT 'zerkalo_test',
            author_name TEXT NOT NULL,
            text TEXT NOT NULL,
            rating INTEGER DEFAULT 5,
            status TEXT DEFAULT 'pending',
            admin_answer TEXT DEFAULT NULL,
            created_at TEXT NOT NULL,
            is_archived INTEGER DEFAULT 0,
            archived_at TEXT DEFAULT NULL
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('retention_months', '6')")

    # 2. Таблица пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT NOT NULL,                    
            access_code TEXT NOT NULL,             
            access_status TEXT DEFAULT 'active',   
            work_status TEXT DEFAULT 'working',    
            created_at TEXT NOT NULL
        )
    """)

    # Авто-создание Владельца
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'owner'")
    if cursor.fetchone()[0] == 0:
        now_str = datetime.now().strftime("%d.%m.%Y, %H:%M")
        cursor.execute(
            "INSERT INTO users (name, role, access_code, created_at) VALUES (?, 'owner', '0000', ?)",
            ("Владелец", now_str),
        )
        print("👑 Создан аккаунт Владельца. Код входа: 0000")

    # 3. Таблица заявок (Leads)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id TEXT DEFAULT 'zerkalo_test',
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT DEFAULT NULL,
            score TEXT DEFAULT NULL,
            messenger_pref TEXT DEFAULT 'Звонок',
            status TEXT DEFAULT 'new',
            locked_by TEXT DEFAULT NULL,
            task_result TEXT DEFAULT NULL,
            comment TEXT DEFAULT NULL,
            created_at TEXT NOT NULL,
            is_archived INTEGER DEFAULT 0,
            archived_at TEXT DEFAULT NULL
        )
    """)

    # МИГРАЦИЯ: если таблица leads уже была без email/score — добавляем колонки
    try:
        cursor.execute("ALTER TABLE leads ADD COLUMN email TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass  # колонка уже есть
    try:
        cursor.execute("ALTER TABLE leads ADD COLUMN score TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass  # колонка уже есть

    # 4. Таблица Сохраненных Отзывов (Золотой Фонд)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_id INTEGER,
            site_id TEXT,
            author_name TEXT,
            text TEXT,
            rating INTEGER,
            admin_answer TEXT,
            created_at TEXT,
            saved_at TEXT NOT NULL
        )
    """)

    # 5. Таблица Сохраненных Заявок (Золотой Фонд)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_id INTEGER,
            site_id TEXT,
            name TEXT,
            phone TEXT,
            messenger_pref TEXT,
            task_result TEXT,
            comment TEXT,
            created_at TEXT,
            saved_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()

# === ФУНКЦИЯ ЖЕЛЕЗОБЕТОННОГО СОХРАНЕНИЯ (АВТО-БЭКАП) ===
def backup_to_json():
    try:
        conn = sqlite3.connect("reviews.db")
        cursor = conn.cursor()
        
        # Бэкап отзывов
        cursor.execute("SELECT * FROM reviews")
        r_rows = cursor.fetchall()
        r_cols = [desc[0] for desc in cursor.description]
        with open("reviews_backup.json", "w", encoding="utf-8") as f:
            json.dump([dict(zip(r_cols, row)) for row in r_rows], f, ensure_ascii=False, indent=4)
            
        # Бэкап заявок
        cursor.execute("SELECT * FROM leads")
        l_rows = cursor.fetchall()
        if l_rows:
            l_cols = [desc[0] for desc in cursor.description]
            with open("leads_backup.json", "w", encoding="utf-8") as f:
                json.dump([dict(zip(l_cols, row)) for row in l_rows], f, ensure_ascii=False, indent=4)
            
        conn.close()
    except Exception as e:
        print(f"⚠️ Ошибка сохранения в файл: {e}")

init_db()
backup_to_json()

# --- МОДЕЛИ ДАННЫХ ---
class ReviewCreate(BaseModel):
    site_id: Optional[str] = 'zerkalo_test'
    author_name: str
    text: str
    rating: Optional[int] = 5

class ReplyCreate(BaseModel):
    admin_answer: str

class LoginRequest(BaseModel):
    access_code: str

class LeadCreate(BaseModel):
    site_id: Optional[str] = 'zerkalo_test'
    name: str
    phone: str
    email: Optional[str] = ""
    score: Optional[str] = ""
    messenger_pref: Optional[str] = 'Звонок'

class LeadLock(BaseModel):
    admin_name: str

class LeadProcess(BaseModel):
    task_result: str
    comment: str

# --- PUSH УВЕДОМЛЕНИЯ ---
def send_push_signal(author_name: str, text: str):
    try:
        url = f"https://ntfy.sh/{PUSH_CHANNEL_ID}"
        req = urllib.request.Request(
            url, data=f"🛡️ Новый отзыв от {author_name}:\n{text}".encode("utf-8"),
            headers={"Click": WEBVIEW_URL, "Priority": "high", "Tags": "star,star2"}
        )
        urllib.request.urlopen(req)
    except: pass

def send_lead_push(name: str, phone: str, pref: str):
    try:
        url = f"https://ntfy.sh/{PUSH_CHANNEL_ID}"
        req = urllib.request.Request(
            url, data=f"📞 Новая заявка!\nИмя: {name}\nТел: {phone}\nСвязь: {pref}".encode("utf-8"),
            headers={"Click": WEBVIEW_URL, "Priority": "high", "Tags": "telephone_receiver,bulb"}
        )
        urllib.request.urlopen(req)
    except: pass

# ================= 📥 ЗАЯВКИ (LEADS) =================
@app.get("/api/leads")
def get_leads():
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    # Отдаем только НЕ архивные
    cursor.execute("SELECT id, site_id, name, phone, email, score, messenger_pref, status, locked_by, task_result, comment, created_at FROM leads WHERE is_archived = 0 ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "site_id": r[1], "name": r[2], "phone": r[3], "email": r[4], "score": r[5],
             "messenger_pref": r[6], "status": r[7], "locked_by": r[8], "task_result": r[9],
             "comment": r[10], "created_at": r[11]} for r in rows]

@app.post("/api/leads")
def create_lead(lead: LeadCreate):
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%d.%m.%Y, %H:%M")
    cursor.execute(
        "INSERT INTO leads (site_id, name, phone, email, score, messenger_pref, status, created_at, is_archived) VALUES (?, ?, ?, ?, ?, ?, 'new', ?, 0)",
        (lead.site_id, lead.name, lead.phone, lead.email, lead.score, lead.messenger_pref, now_str)
    )
    conn.commit()
    conn.close()
    backup_to_json()
    send_lead_push(lead.name, lead.phone, lead.messenger_pref)
    return {"message": "Заявка успешно создана"}

@app.put("/api/leads/{lead_id}/lock")
def lock_lead(lead_id: int, data: LeadLock):
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE leads SET status = 'in_progress', locked_by = ? WHERE id = ? AND status = 'new'", (data.admin_name, lead_id))
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    backup_to_json()
    if rows_affected == 0: raise HTTPException(status_code=400, detail="Уже в работе")
    return {"message": "Взято в работу"}

@app.put("/api/leads/{lead_id}/complete")
def complete_lead(lead_id: int, data: LeadProcess):
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE leads SET status = 'completed', task_result = ?, comment = ? WHERE id = ?", (data.task_result, data.comment, lead_id))
    conn.commit()
    conn.close()
    backup_to_json()
    return {"message": "Заявка обработана"}

@app.put("/api/leads/{lead_id}/archive")
def archive_lead(lead_id: int):
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%d.%m.%Y, %H:%M")
    cursor.execute("UPDATE leads SET is_archived = 1, archived_at = ? WHERE id = ?", (now_str, lead_id))
    conn.commit()
    conn.close()
    backup_to_json()
    return {"message": "Заявка в архиве"}

@app.put("/api/leads/{lead_id}/reopen")
def reopen_lead(lead_id: int):
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE leads SET status = 'new', locked_by = NULL, task_result = NULL, comment = NULL WHERE id = ?", (lead_id,))
    conn.commit()
    conn.close()
    backup_to_json()
    return {"message": "Заявка возвращена в новые"}

# ================= ОТЗЫВЫ =================
@app.get("/api/reviews")
def get_reviews(is_archived: int = 0):
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, site_id, author_name, text, rating, status, admin_answer, created_at FROM reviews WHERE is_archived=? ORDER BY id DESC", (is_archived,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "site_id": r[1], "author_name": r[2], "text": r[3], "rating": r[4], "status": r[5], "admin_answer": r[6], "created_at": r[7]} for r in rows]

@app.post("/api/reviews")
def create_review(review: ReviewCreate):
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%d.%m.%Y, %H:%M")
    cursor.execute("INSERT INTO reviews (site_id, author_name, text, rating, status, created_at, is_archived) VALUES (?, ?, ?, ?, 'pending', ?, 0)", (review.site_id, review.author_name, review.text, review.rating, now_str))
    conn.commit()
    conn.close()
    backup_to_json()
    send_push_signal(review.author_name, review.text)
    return {"message": "Отзыв отправлен"}

@app.put("/api/reviews/{review_id}/approve")
def approve_review(review_id: int):
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE reviews SET status = 'approved' WHERE id = ?", (review_id,))
    conn.commit()
    conn.close()
    backup_to_json()
    return {"message": "Одобрено"}

@app.put("/api/reviews/{review_id}/reply")
def reply_review(review_id: int, reply: ReplyCreate):
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE reviews SET status = 'approved', admin_answer = ? WHERE id = ?", (reply.admin_answer, review_id))
    conn.commit()
    conn.close()
    backup_to_json()
    return {"message": "Ответ сохранен"}

@app.put("/api/reviews/{review_id}/archive")
def archive_review(review_id: int):
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%d.%m.%Y, %H:%M")
    cursor.execute("UPDATE reviews SET is_archived = 1, archived_at = ? WHERE id = ?", (now_str, review_id))
    conn.commit()
    conn.close()
    backup_to_json()
    return {"message": "Перемещено в архив"}

@app.delete("/api/reviews/{review_id}")
def delete_review(review_id: int):
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
    conn.commit()
    conn.close()
    backup_to_json()
    return {"message": "Удален"}

# ================= АРХИВ И НАСТРОЙКИ (GET) =================
@app.get("/api/archive/reviews")
def get_archive_reviews():
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, site_id, author_name, text, rating, status, admin_answer, created_at, archived_at FROM reviews WHERE is_archived=1 ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "site_id": r[1], "author_name": r[2], "text": r[3], "rating": r[4], "status": r[5], "admin_answer": r[6], "created_at": r[7], "archived_at": r[8]} for r in rows]

@app.get("/api/archive/leads")
def get_archive_leads():
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, site_id, name, phone, messenger_pref, status, task_result, comment, created_at, archived_at FROM leads WHERE is_archived=1 ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "site_id": r[1], "name": r[2], "phone": r[3], "messenger_pref": r[4], "status": r[5], "task_result": r[6], "comment": r[7], "created_at": r[8], "archived_at": r[9]} for r in rows]

# ================= ⭐️ СОХРАНЁННЫЕ (ЗОЛОТОЙ ФОНД) =================
# Отзывы
@app.get("/api/saved")
def get_saved():
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, original_id, author_name, text, admin_answer, created_at FROM saved_reviews ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "original_id": r[1], "author_name": r[2], "text": r[3], "admin_answer": r[4], "created_at": r[5]} for r in rows]

@app.post("/api/saved/{review_id}")
def save_review(review_id: int):
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, site_id, author_name, text, rating, admin_answer, created_at FROM reviews WHERE id = ?", (review_id,))
    r = cursor.fetchone()
    if not r: raise HTTPException(status_code=404, detail="Не найден")
    cursor.execute("SELECT COUNT(*) FROM saved_reviews WHERE original_id = ?", (review_id,))
    if cursor.fetchone()[0] > 0: return {"already": True}
    now_str = datetime.now().strftime("%d.%m.%Y, %H:%M")
    cursor.execute("INSERT INTO saved_reviews (original_id, site_id, author_name, text, rating, admin_answer, created_at, saved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (r[0], r[1], r[2], r[3], r[4], r[5], r[6], now_str))
    conn.commit()
    conn.close()
    return {"message": "Сохранён"}

@app.delete("/api/saved/{saved_id}")
def delete_saved(saved_id: int):
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM saved_reviews WHERE id = ?", (saved_id,))
    conn.commit()
    conn.close()
    return {"message": "Удалено"}

# Заявки
@app.get("/api/saved_leads")
def get_saved_leads():
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, original_id, name, phone, messenger_pref, task_result, comment, created_at FROM saved_leads ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "original_id": r[1], "name": r[2], "phone": r[3], "messenger_pref": r[4], "task_result": r[5], "comment": r[6], "created_at": r[7]} for r in rows]

@app.post("/api/saved_leads/{lead_id}")
def save_lead(lead_id: int):
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, site_id, name, phone, messenger_pref, task_result, comment, created_at FROM leads WHERE id = ?", (lead_id,))
    r = cursor.fetchone()
    if not r: raise HTTPException(status_code=404, detail="Не найдена")
    cursor.execute("SELECT COUNT(*) FROM saved_leads WHERE original_id = ?", (lead_id,))
    if cursor.fetchone()[0] > 0: return {"already": True}
    now_str = datetime.now().strftime("%d.%m.%Y, %H:%M")
    cursor.execute("INSERT INTO saved_leads (original_id, site_id, name, phone, messenger_pref, task_result, comment, created_at, saved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], now_str))
    conn.commit()
    conn.close()
    return {"message": "Сохранена"}

@app.delete("/api/saved_leads/{saved_id}")
def delete_saved_lead(saved_id: int):
    conn = sqlite3.connect("reviews.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM saved_leads WHERE id = ?", (saved_id,))
    conn.commit()
    conn.close()
    return {"message": "Удалено"}
