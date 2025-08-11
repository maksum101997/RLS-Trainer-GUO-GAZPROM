import math
from datetime import datetime, timedelta
import time
from PyQt5.QtCore import QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QTransform
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFormLayout, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QDialog, QLineEdit, QDialogButtonBox, QComboBox, QDoubleSpinBox, QCheckBox
)
from db import DB
from dialogs import TrainingSettings
from graphics import MapScene, MapView
def minutes_to_seconds(minutes: float) -> int:
    return int(math.ceil(minutes * 60))

def format_mm_ss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"
class TrainingTimer(QObject):
    tick = pyqtSignal(int)
    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._duration = 0
        self._deadline = None
        self._remaining_paused = 0
        self._running = False
        self._qtimer = QTimer(self)
        self._qtimer.setInterval(250)
        self._qtimer.timeout.connect(self._on_tick)

    def start_minutes(self, minutes: float):
        self.start_seconds(minutes_to_seconds(minutes))

    def start_seconds(self, seconds: int):
        self._duration = int(seconds)
        self._deadline = time.monotonic() + self._duration
        self._remaining_paused = 0
        self._running = True
        self._qtimer.start()
        self._on_tick()

    def pause(self):
        if not self._running:
            return
        remaining = self.remaining_seconds()
        self._remaining_paused = remaining
        self._running = False
        self._qtimer.stop()

    def resume(self):
        if self._running or self._remaining_paused <= 0:
            return
        self._deadline = time.monotonic() + self._remaining_paused
        self._remaining_paused = 0
        self._running = True
        self._qtimer.start()
        self._on_tick()

    def stop(self):
        self._running = False
        self._qtimer.stop()
        self._deadline = None
        self._remaining_paused = 0

    def is_running(self) -> bool:
        return self._running

    def remaining_seconds(self) -> int:
        if self._running and self._deadline is not None:
            return max(0, int(math.ceil(self._deadline - time.monotonic())))
        return max(0, int(self._remaining_paused))

    def _on_tick(self):
        rem = self.remaining_seconds()
        self.tick.emit(rem)
        if rem <= 0 and self._running:
            self._running = False
            self._qtimer.stop()
            self.finished.emit()

class TrainingView(QWidget):
    finished = pyqtSignal(int, int, str, int)  # correct, wrong, started_at_iso, duration_sec
    def __init__(self, db: DB, parent_main):
        super().__init__(db, parent_main)


        self.map_view.objectClicked.connect(self.on_object_clicked)

    def on_object_clicked(self, obj):
        """Метод, вызываемый при клике на объект. Отображает информацию о нем."""
        if obj:
            self.follow_object = obj
            self.parent_main.show_object_info(obj)  # Показываем информацию о выбранном объекте
        else:
            self.follow_object = None
            self.parent_main.hide_object_info()
    def __init__(self, db: DB, parent_main):
        super().__init__()
        self.db = db
        self.parent_main = parent_main
        self.scene = MapScene(db, max_objects_limit=12)
        self.map_view = MapView(self.scene)
        self.map_view.targetIdentified.connect(self.on_identified)

        left = QVBoxLayout()
        btn_draw_detect = QPushButton("Добавить зону обнаружения")
        btn_draw_ignore = QPushButton("Добавить зону игнора")
        btn_cancel_draw = QPushButton("Отменить рисование зоны")
        btn_settings = QPushButton("Настройки тренировки")
        left.addWidget(btn_settings)
        left.addSpacing(12)
        left.addWidget(btn_draw_detect)
        left.addWidget(btn_draw_ignore)
        left.addWidget(btn_cancel_draw)
        left.addStretch()

        btn_draw_detect.clicked.connect(lambda: self.scene.start_draw_zone("detect"))
        btn_draw_ignore.clicked.connect(lambda: self.scene.start_draw_zone("ignore"))
        btn_cancel_draw.clicked.connect(self.scene.cancel_temp_zone)
        btn_settings.clicked.connect(self.open_settings)

        top = QHBoxLayout()
        self.btn_pause = QPushButton("Пауза")
        self.btn_compass = QPushButton("Компас (North-Up)")
        self.btn_home = QPushButton("Дом")
        self.lbl_time = QLabel("--:--:--")
        self.lbl_time.setStyleSheet("color: #A2E1FF; font-weight: bold;")
        top.addWidget(self.btn_pause)
        top.addSpacing(12)
        top.addWidget(self.btn_compass)
        top.addWidget(self.btn_home)
        top.addStretch()
        top.addWidget(QLabel("Время:"))
        top.addWidget(self.lbl_time)

        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_compass.clicked.connect(self.map_view.north_up)
        self.btn_home.clicked.connect(lambda: self.map_view.reset_to_home(self.db))

        center_layout = QVBoxLayout()
        center_layout.addLayout(top)
        center_layout.addWidget(self.map_view)

        root = QHBoxLayout()
        side_panel = QWidget()
        side_box = QVBoxLayout()
        side_box.addLayout(left)
        side_panel.setLayout(side_box)
        side_panel.setFixedWidth(240)

        root.addWidget(side_panel)
        root.addLayout(center_layout)
        self.setLayout(root)

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)

        self.sim_timer = QTimer(self)
        self.sim_timer.timeout.connect(self.on_tick)

        self.spawn_timer = QTimer(self)
        self.spawn_timer.timeout.connect(self.on_spawn)

        self.session_active = False
        self.session_end_time = None
        self.session_started_at = None
        self.correct = 0
        self.wrong = 0
        self.session_settings = {
            "time_limit": 120,
            "max_objects": 12,
            "bvs_ratio": 0.5,
            "show_traj": True,
            "show_heading": True
        }
        # Текущий объект, за которым ведётся слежение (при клике)
        self.follow_object = None

        # Подключаем сигнал клика по объекту из MapView
        try:
            self.map_view.objectClicked.connect(self.on_object_clicked)
        except Exception:
            pass

        self.map_view.reset_to_home(self.db)

    def update_clock(self):
        now = datetime.now().strftime("%H:%M:%S")
        self.lbl_time.setText(now)

    def open_settings(self):
        dlg = TrainingSettings(self.db, self, max_objects_limit=100)
        s = dlg.get()
        if s:
            self.session_settings.update(s)
            # сохраняем глобальные флаги отображения
            self.db.save_settings(show_trajectory=int(s["show_traj"]),
                                  show_heading=int(s["show_heading"]))
            # применяем в сцене
            self.scene.set_show_flags(s["show_traj"], s["show_heading"])
            self.scene.max_objects_limit = s["max_objects"]
            self.start_session()

    def start_session(self):
        self.scene.set_show_flags(self.session_settings["show_traj"], self.session_settings["show_heading"])
        self.scene.max_objects_limit = self.session_settings["max_objects"]
        self.correct = 0
        self.wrong = 0
        self.parent_main.add_notification("Сеанс тренировки начат")
        self.session_active = True
        self.session_started_at = datetime.now()
        self.session_end_time = self.session_started_at + timedelta(seconds=self.session_settings["time_limit"])
        for obj in list(self.scene.objects):
            self.scene.remove_object(obj)
        self.sim_timer.start(33)
        self.spawn_timer.start(1000)
        self.btn_pause.setText("Пауза")

        # Сброс режима слежения при запуске новой сессии
        self.follow_object = None
        try:
            self.parent_main.hide_object_info()
        except Exception:
            pass

    def end_session(self):
        if not self.session_active:
            return
        self.session_active = False
        self.sim_timer.stop()
        self.spawn_timer.stop()
        self.parent_main.add_notification("Сеанс тренировки завершён")
        duration = int((datetime.now() - self.session_started_at).total_seconds()) if self.session_started_at else 0
        self.finished.emit(self.correct, self.wrong,
                           self.session_started_at.isoformat(timespec='seconds') if self.session_started_at else datetime.now().isoformat(timespec='seconds'),
                           duration)

        # Завершаем режим слежения при окончании сессии
        self.follow_object = None
        try:
            self.parent_main.hide_object_info()
        except Exception:
            pass

    def toggle_pause(self):
        if not self.session_active:
            return
        if self.sim_timer.isActive():
            self.sim_timer.stop()
            self.spawn_timer.stop()
            self.btn_pause.setText("Продолжить")
            self.parent_main.add_notification("Пауза")
        else:
            self.sim_timer.start(33)
            self.spawn_timer.start(1000)
            self.btn_pause.setText("Пауза")
            self.parent_main.add_notification("Продолжить")

    def on_tick(self):
        if not self.session_active:
            return
        now = datetime.now()
        if now >= self.session_end_time:
            self.end_session()
            return
        self.scene.tick(0.033, self.parent_main)

        # Если есть выбранный объект, обновляем информацию или прекращаем слежение
        if self.follow_object:
            # Проверяем, что объект всё ещё существует в сцене
            if self.follow_object in self.scene.objects:
                try:
                    self.parent_main.update_object_info(self.follow_object)
                except Exception:
                    pass
            else:
                # Объект был удалён — прекращаем режим слежения
                self.follow_object = None
                try:
                    self.parent_main.hide_object_info()
                except Exception:
                    pass

    def on_spawn(self):
        if not self.session_active:
            return
        if len(self.scene.objects) < self.session_settings["max_objects"]:
            self.scene.spawn_random_object(self.session_settings["bvs_ratio"])

    def on_identified(self, correct: bool):
        if not self.session_active:
            return
        if correct:
            self.correct += 1
            self.parent_main.add_notification("Верно: объект БВС определён")
        else:
            self.wrong += 1
            self.parent_main.add_notification("Неверно: это не БВС")

    def on_object_clicked(self, obj):
        """
        Вызывается при одиночном клике на объект. Если объект существует,
        активируем режим слежения, сохраняя ссылку на объект и запрашивая
        отображение информации о нём. Если передан None, прекращаем режим
        слежения и скрываем информацию.
        """
        # Не реагируем, если сессия не запущена
        if not self.session_active:
            return
        if obj:
            self.follow_object = obj
            try:
                self.parent_main.show_object_info(obj)
            except Exception:
                pass
        else:
            # Клик по пустому месту — прекращаем слежение
            self.follow_object = None
            try:
                self.parent_main.hide_object_info()
            except Exception:
                pass


class ProfileView(QWidget):
    def __init__(self, db: DB):
        super().__init__()
        self.db = db
        self.user = None

        layout = QVBoxLayout()
        self.lbl_user = QLabel("Профиль: -")
        self.lbl_role = QLabel("Роль: -")
        layout.addWidget(self.lbl_user)
        layout.addWidget(self.lbl_role)

        layout.addWidget(QLabel("История тренировок:"))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Начало", "Длительность (с)", "Верно", "Ошибки", "Точность"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        self.setLayout(layout)

    def set_user(self, user):
        self.user = user
        self.lbl_user.setText(f"Профиль: {user['username']}")
        self.lbl_role.setText(f"Роль: {'Администратор' if user['role']=='admin' else 'Оператор'}")
        self.reload_history()

    def reload_history(self):
        if not self.user:
            return
        rows = self.db.get_trainings(self.user["id"])
        self.table.setRowCount(0)
        for r in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            self.table.setItem(i, 0, QTableWidgetItem(r["started_at"]))
            self.table.setItem(i, 1, QTableWidgetItem(str(r["duration_sec"])))
            self.table.setItem(i, 2, QTableWidgetItem(str(r["correct"])))
            self.table.setItem(i, 3, QTableWidgetItem(str(r["wrong"])))
            self.table.setItem(i, 4, QTableWidgetItem(f"{(r['accuracy']*100):.1f}%"))


class SettingsView(QWidget):
    def __init__(self, db: DB, main_window):
        super().__init__()
        self.db = db
        self.main = main_window
        self.user = None

        root = QVBoxLayout()

        # Users (admin)
        self.user_box = QGroupBox("Пользователи (Админ)")
        u_layout = QVBoxLayout()
        self.users_table = QTableWidget(0, 3)
        self.users_table.setHorizontalHeaderLabels(["id", "Логин", "Роль"])
        self.users_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        btns = QHBoxLayout()
        self.btn_add_user = QPushButton("Добавить пользователя")
        self.btn_change_role = QPushButton("Сменить роль")
        self.btn_reset_password = QPushButton("Сбросить пароль")
        btns.addWidget(self.btn_add_user)
        btns.addWidget(self.btn_change_role)
        btns.addWidget(self.btn_reset_password)
        u_layout.addWidget(self.users_table)
        u_layout.addLayout(btns)
        self.user_box.setLayout(u_layout)

        # Preferences
        pref_box = QGroupBox("Настройки приложения")
        p_layout = QFormLayout()
        s = self.db.get_settings()
        self.chk_traj = QCheckBox()
        self.chk_traj.setChecked(bool(s["show_trajectory"]))
        self.chk_heading = QCheckBox()
        self.chk_heading.setChecked(bool(s["show_heading"]))
        self.spin_volume = QDoubleSpinBox()
        self.spin_volume.setRange(0.0, 1.0)
        self.spin_volume.setSingleStep(0.1)
        self.spin_volume.setValue(float(s["sound_volume"]))
        p_layout.addRow("Показывать траектории:", self.chk_traj)
        p_layout.addRow("Показывать направление:", self.chk_heading)
        p_layout.addRow("Громкость (0..1):", self.spin_volume)
        self.btn_save_pref = QPushButton("Сохранить настройки")
        p_layout.addRow(self.btn_save_pref)
        pref_box.setLayout(p_layout)

        # Home position
        home_box = QGroupBox("Позиция")
        h_layout = QHBoxLayout()
        self.btn_set_home = QPushButton("Установить Дом в центр/масштаб текущей карты (из Тренировки)")
        h_layout.addWidget(self.btn_set_home)
        home_box.setLayout(h_layout)

        root.addWidget(self.user_box)
        root.addWidget(pref_box)
        root.addWidget(home_box)
        root.addStretch()
        self.setLayout(root)

        # Signals
        self.btn_add_user.clicked.connect(self.on_add_user)
        self.btn_change_role.clicked.connect(self.on_change_role)
        self.btn_reset_password.clicked.connect(self.on_reset_password)
        self.btn_save_pref.clicked.connect(self.on_save_prefs)
        self.btn_set_home.clicked.connect(self.on_set_home)

        self.refresh_users()

    def set_user(self, user):
        self.user = user
        self.user_box.setVisible(user["role"] == "admin")

    def refresh_users(self):
        self.users_table.setRowCount(0)
        for u in self.db.list_users():
            i = self.users_table.rowCount()
            self.users_table.insertRow(i)
            self.users_table.setItem(i, 0, QTableWidgetItem(str(u["id"])))
            self.users_table.setItem(i, 1, QTableWidgetItem(u["username"]))
            self.users_table.setItem(i, 2, QTableWidgetItem(u["role"]))

    # остальной код без изменений (диалоги и сохранение настроек) — у тебя уже корректный
    def on_add_user(self):
        if self.user["role"] != "admin":
            QMessageBox.warning(self, "Доступ", "Только администратор")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Добавить пользователя")
        form = QFormLayout()
        login = QLineEdit()
        pwd = QLineEdit()
        pwd.setEchoMode(QLineEdit.Password)
        role = QComboBox()
        role.addItems(["operator", "admin"])
        form.addRow("Логин:", login)
        form.addRow("Пароль:", pwd)
        form.addRow("Роль:", role)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        v = QVBoxLayout()
        v.addLayout(form)
        v.addWidget(btns)
        dlg.setLayout(v)
        if dlg.exec_() == QDialog.Accepted:
            ok = self.db.create_user(login.text().strip(), pwd.text().strip(), role.currentText())
            if not ok:
                QMessageBox.warning(self, "Ошибка", "Логин занят")
            self.refresh_users()

    def on_change_role(self):
        if self.user["role"] != "admin":
            QMessageBox.warning(self, "Доступ", "Только администратор")
            return
        row = self.users_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Выбор", "Выберите пользователя в таблице")
            return
        uid = int(self.users_table.item(row, 0).text())
        uname = self.users_table.item(row, 1).text()
        current_role = self.users_table.item(row, 2).text()

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Смена роли: {uname}")
        form = QFormLayout()
        role = QComboBox()
        role.addItems(["operator", "admin"])
        role.setCurrentText(current_role)
        form.addRow("Роль:", role)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        v = QVBoxLayout()
        v.addLayout(form)
        v.addWidget(btns)
        dlg.setLayout(v)
        if dlg.exec_() == QDialog.Accepted:
            self.db.set_user_role(uid, role.currentText())
            self.refresh_users()

    def on_reset_password(self):
        if self.user["role"] != "admin":
            QMessageBox.warning(self, "Доступ", "Только администратор")
            return
        row = self.users_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Выбор", "Выберите пользователя в таблице")
            return
        uid = int(self.users_table.item(row, 0).text())
        uname = self.users_table.item(row, 1).text()

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Сброс пароля: {uname}")
        form = QFormLayout()
        pwd1 = QLineEdit()
        pwd2 = QLineEdit()
        pwd1.setEchoMode(QLineEdit.Password)
        pwd2.setEchoMode(QLineEdit.Password)
        form.addRow("Новый пароль:", pwd1)
        form.addRow("Повтор пароля:", pwd2)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        v = QVBoxLayout()
        v.addLayout(form)
        v.addWidget(btns)
        dlg.setLayout(v)

        if dlg.exec_() == QDialog.Accepted:
            if pwd1.text().strip() == "" or pwd1.text() != pwd2.text():
                QMessageBox.warning(self, "Пароль", "Пароли пустые или не совпадают")
                return
            self.db.change_password(uid, pwd1.text().strip())
            QMessageBox.information(self, "Пароль", "Пароль обновлён")

    def on_save_prefs(self):
        self.db.save_settings(show_trajectory=int(self.chk_traj.isChecked()),
                              show_heading=int(self.chk_heading.isChecked()),
                              sound_volume=float(self.spin_volume.value()))
        try:
            self.main.training_view.scene.set_show_flags(self.chk_traj.isChecked(), self.chk_heading.isChecked())
            self.main.add_notification("Настройки сохранены")
        except Exception:
            pass

    def on_set_home(self):
        mv = self.main.training_view.map_view
        center_scene = mv.mapToScene(mv.viewport().rect().center())
        t: QTransform = mv.transform()
        scale_x = math.hypot(t.m11(), t.m12())
        self.db.save_settings(home_x=center_scene.x(), home_y=center_scene.y(), home_scale=scale_x)
        self.main.add_notification("Домашняя позиция сохранена")
