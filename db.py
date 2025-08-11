import sqlite3
import hashlib
from datetime import datetime

DB_NAME = "rls_trainer.db"


class DB:
    def __init__(self, path=DB_NAME):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        c = self.conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT,
            role TEXT CHECK(role IN ('admin','operator')) NOT NULL DEFAULT 'operator'
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS trainings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            started_at TEXT,
            duration_sec INTEGER,
            correct INTEGER,
            wrong INTEGER,
            accuracy REAL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            created_at TEXT,
            type TEXT,
            message TEXT,
            screenshot_path TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id=1),
            home_x REAL,
            home_y REAL,
            home_scale REAL,
            show_trajectory INTEGER,
            show_heading INTEGER,
            sound_volume REAL
        )""")
        self.conn.commit()
        if not self.get_user_by_username("admin"):
            self.create_user("admin", "admin", "admin")
        if not self.get_settings():
            self.save_settings(home_x=0.0, home_y=0.0, home_scale=1.0,
                               show_trajectory=1, show_heading=1, sound_volume=0.5)

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def hash_pwd(self, pwd):
        return hashlib.sha256(pwd.encode("utf-8")).hexdigest()

    def create_user(self, username, password, role="operator"):
        try:
            c = self.conn.cursor()
            c.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                      (username, self.hash_pwd(password), role))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_user_by_username(self, username):
        c = self.conn.cursor()
        c.execute("SELECT * FROM users WHERE username=?", (username,))
        return c.fetchone()

    def validate_login(self, username, password):
        u = self.get_user_by_username(username)
        if not u:
            return None
        if u["password_hash"] == self.hash_pwd(password):
            return u
        return None

    def change_password(self, user_id, new_password):
        c = self.conn.cursor()
        c.execute("UPDATE users SET password_hash=? WHERE id=?",
                  (self.hash_pwd(new_password), user_id))
        self.conn.commit()

    def list_users(self):
        c = self.conn.cursor()
        c.execute("SELECT id, username, role FROM users ORDER BY username")
        return c.fetchall()

    def set_user_role(self, user_id, role):
        c = self.conn.cursor()
        c.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
        self.conn.commit()

    def add_training(self, user_id, started_at, duration_sec, correct, wrong):
        total = correct + wrong
        accuracy = (correct / total) if total > 0 else 0.0
        c = self.conn.cursor()
        c.execute("""INSERT INTO trainings(user_id,started_at,duration_sec,correct,wrong,accuracy)
                     VALUES(?,?,?,?,?,?)""",
                  (user_id, started_at, duration_sec, correct, wrong, accuracy))
        self.conn.commit()

    def get_trainings(self, user_id):
        c = self.conn.cursor()
        c.execute("""SELECT started_at, duration_sec, correct, wrong, accuracy
                     FROM trainings WHERE user_id=? ORDER BY id DESC""", (user_id,))
        return c.fetchall()

    def add_event(self, user_id, type_, message, screenshot_path):
        c = self.conn.cursor()
        c.execute("""INSERT INTO events(user_id, created_at, type, message, screenshot_path)
                     VALUES(?,?,?,?,?)""",
                  (user_id, datetime.now().isoformat(timespec='seconds'), type_, message, screenshot_path))
        self.conn.commit()

    def get_settings(self):
        c = self.conn.cursor()
        c.execute("SELECT * FROM settings WHERE id=1")
        return c.fetchone()

    def save_settings(self, home_x=None, home_y=None, home_scale=None,
                      show_trajectory=None, show_heading=None, sound_volume=None):
        current = self.get_settings()
        if current:
            home_x = current["home_x"] if home_x is None else home_x
            home_y = current["home_y"] if home_y is None else home_y
            home_scale = current["home_scale"] if home_scale is None else home_scale
            show_trajectory = current["show_trajectory"] if show_trajectory is None else int(show_trajectory)
            show_heading = current["show_heading"] if show_heading is None else int(show_heading)
            sound_volume = current["sound_volume"] if sound_volume is None else float(sound_volume)
            c = self.conn.cursor()
            c.execute("""UPDATE settings SET home_x=?, home_y=?, home_scale=?, 
                         show_trajectory=?, show_heading=?, sound_volume=? WHERE id=1""",
                      (home_x, home_y, home_scale, show_trajectory, show_heading, sound_volume))
            self.conn.commit()
        else:
            c = self.conn.cursor()
            c.execute("""INSERT INTO settings(id,home_x,home_y,home_scale,show_trajectory,show_heading,sound_volume)
                         VALUES(1,?,?,?,?,?,?)""",
                      (home_x or 0.0, home_y or 0.0, home_scale or 1.0,
                       int(show_trajectory or 1), int(show_heading or 1), float(sound_volume or 0.5)))
            self.conn.commit()
