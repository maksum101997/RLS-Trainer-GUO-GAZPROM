from PyQt5.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QVBoxLayout,
    QMessageBox, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton
)
from PyQt5.QtCore import Qt, QPoint
from db import DB


from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QDialogButtonBox,
    QLabel, QLineEdit, QMessageBox
)
from PyQt5.QtGui import QPixmap, QPalette, QBrush
from PyQt5.QtCore import Qt

class LoginDialog(QDialog):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.setWindowTitle("Авторизация")
        self.resize(320, 140)

        # Поля ввода
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)

        # Стили для полей
        self.username.setStyleSheet("""
            background-color: white;
            padding: 4px;
            border-radius: 4px;
            color: black;
        """)
        self.password.setStyleSheet("""
            background-color: white;
            padding: 4px;
            border-radius: 4px;
            color: black;
        """)

        # Метки с белым текстом
        login_label = QLabel("Логин:")
        login_label.setStyleSheet("color: white; font-weight: bold;")
        password_label = QLabel("Пароль:")
        password_label.setStyleSheet("color: white; font-weight: bold;")

        # Формы
        form = QFormLayout()
        form.addRow(login_label, self.username)
        form.addRow(password_label, self.password)

        # Кнопки
        self.btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btns.accepted.connect(self.try_login)
        self.btns.rejected.connect(self.reject)

        # Layout
        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.btns)
        self.setLayout(layout)

        # Установка фонового изображения
        self.update_background()

        # Переменная для хранения пользователя
        self._user = None

    def update_background(self):
        bg = QPixmap("assets/fon.png").scaled(
            self.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation
        )
        palette = QPalette()
        palette.setBrush(QPalette.Window, QBrush(bg))
        self.setPalette(palette)

    def resizeEvent(self, event):
        self.update_background()
        super().resizeEvent(event)

    def try_login(self):
        login = self.username.text().strip()
        password = self.password.text().strip()

        if not login or not password:
            QMessageBox.warning(self, "Ошибка", "Введите логин и пароль")
            return

        try:
            user = self.db.validate_login(login, password)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка БД", f"Ошибка при обращении к базе: {e}")
            return

        if not user:
            QMessageBox.warning(self, "Ошибка входа", "Неверный логин или пароль")
            return

        self._user = user
        self.accept()

    def get_user(self):
        result = self.exec_()
        return self._user if result == QDialog.Accepted else None



class TrainingSettings(QDialog):
    def __init__(self, db: DB, parent=None, max_objects_limit=20):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Настройки тренировки")

        self.time_limit = QSpinBox()
        self.time_limit.setRange(10, 3600)
        self.time_limit.setValue(120)

        self.max_objects = QSpinBox()
        self.max_objects.setRange(1, max_objects_limit)
        self.max_objects.setValue(12)

        self.bvs_ratio = QDoubleSpinBox()
        self.bvs_ratio.setRange(0.0, 1.0)
        self.bvs_ratio.setSingleStep(0.05)
        self.bvs_ratio.setValue(0.5)

        # Безопасный просмотр настройки из БД
        try:
            s = self.db.get_settings()
            show_traj_default = bool(s["show_trajectory"])
            show_heading_default = bool(s["show_heading"])
        except Exception:
            show_traj_default = True
            show_heading_default = True

        self.show_traj = QCheckBox("Показывать траекторию объектов")
        self.show_traj.setChecked(show_traj_default)
        self.show_heading = QCheckBox("Показывать направление движения")
        self.show_heading.setChecked(show_heading_default)

        form = QFormLayout()
        form.addRow("Ограничение по времени (сек):", self.time_limit)
        form.addRow("Максимум объектов на карте:", self.max_objects)
        form.addRow("Доля БВС:", self.bvs_ratio)
        form.addRow(self.show_traj)
        form.addRow(self.show_heading)

        self.btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btns.accepted.connect(self.accept)
        self.btns.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.btns)
        self.setLayout(layout)
        self.resize(400, 240)
        self.setStyleSheet("""
    QDialog {
        background-image: url(assets/2.png);  /* путь к изображению */
        background-repeat: no-repeat;
        background-position: center;
        background-size: cover;
    }
""")

    def get(self):
        if self.exec_() == QDialog.Accepted:
            return {
                "time_limit": self.time_limit.value(),
                "max_objects": self.max_objects.value(),
                "bvs_ratio": float(self.bvs_ratio.value()),
                "show_traj": self.show_traj.isChecked(),
                "show_heading": self.show_heading.isChecked()
            }
        return None


class ActionPopup(QDialog):
    """
    Неблокирующее всплывающее окно выбора действия над объектом.
    Ничего не делает с объектом/сценой напрямую — только возвращает выбранное действие.
    Это гарантирует отсутствие ошибок, если методы сцены/объекта отличаются.

    Использование:
        action = ActionPopup.get_action(obj, parent=self, global_pos=QCursor.pos())
        if action == ActionPopup.ACTION_TRACK:
            ...
    """
    ACTION_TRACK = "track"
    ACTION_SUPPRESS = "suppress"
    ACTION_ECM = "ecm"
    ACTION_DELETE = "delete"
    ACTION_CANCEL = None

    def __init__(self, obj, parent=None):
        super().__init__(parent)
        self.obj = obj
        self.chosen_action = self.ACTION_CANCEL

        # Ведём себя как всплывающее меню рядом с курсором
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setWindowTitle("Действие")

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        btn_track = QPushButton("Сопровождать")
        btn_track.clicked.connect(lambda: self._choose(self.ACTION_TRACK))
        layout.addWidget(btn_track)

        btn_suppress = QPushButton("Подавить")
        btn_suppress.clicked.connect(lambda: self._choose(self.ACTION_SUPPRESS))
        layout.addWidget(btn_suppress)

        btn_ecm = QPushButton("ECM")
        btn_ecm.clicked.connect(lambda: self._choose(self.ACTION_ECM))
        layout.addWidget(btn_ecm)

        btn_delete = QPushButton("Удалить")
        btn_delete.clicked.connect(lambda: self._choose(self.ACTION_DELETE))
        layout.addWidget(btn_delete)

        self.setLayout(layout)
        self.adjustSize()

    def _choose(self, action: str):
        self.chosen_action = action
        self.accept()

    @classmethod
    def get_action(cls, obj, parent=None, global_pos: QPoint = None):
        """
        Открывает всплывающее окно и возвращает выбранное действие как строку,
        либо None, если пользователь отменил/кликнул мимо.
        """
        dlg = cls(obj=obj, parent=parent)
        if global_pos is not None:
            # Расположим окно рядом с курсором
            dlg.move(global_pos)
        result = dlg.exec_()
        return dlg.chosen_action if result == QDialog.Accepted else cls.ACTION_CANCEL
