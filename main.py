import sys
import os
from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QAction, QToolBar,
    QMessageBox, QFileDialog, QLabel, QDockWidget
)

from db import DB
from dialogs import LoginDialog
from widgets import NotificationsDock
from views import TrainingView, ProfileView, SettingsView


APP_TITLE = "RLS Trainer"

class MainWindow(QMainWindow):
    def __init__(self, db: DB, user):
        super().__init__()
        self.db = db
        self.user = user
        self.setWindowTitle(APP_TITLE)
        self.resize(1200, 800)
        # Создание панели справа для информации о дроне
        self.object_info_label = QLabel()
        self.object_info_label.setWordWrap(True)
        self.object_info_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.object_info_label.setStyleSheet("padding: 6px; color: black;")
        self.object_info_dock = QDockWidget("Информация о дроне", self)
        self.object_info_dock.setWidget(self.object_info_label)
        self.object_info_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self.object_info_dock)
class MainWindow(QMainWindow):
    def __init__(self, db: DB, user):
        super().__init__()
        self.db = db
        self.user = user
        self.setWindowTitle(APP_TITLE)
        self.resize(1200, 800)
        
        # Центр — стек с представлениями
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        # Представления
        self.training_view = TrainingView(self.db, self)
        self.profile_view = ProfileView(self.db)
        self.settings_view = SettingsView(self.db, self)

        self.stack.addWidget(self.training_view)
        self.stack.addWidget(self.profile_view)
        self.stack.addWidget(self.settings_view)

        self.profile_view.set_user(self.user)
        self.settings_view.set_user(self.user)
        # Уведомления
        self.notifications = NotificationsDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.notifications)

        # Панель информации о выбранном объекте (режим слежения)
        # Создаём док с меткой, которая будет содержать текст статистики.
        self.object_info_label = QLabel()
        # Многострочный текст; перенос строки позволяет тексту помещаться по ширине
        self.object_info_label.setWordWrap(True)
        self.object_info_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        # Стиль: оставим цвет как у уведомлений, чтобы была консистентность
        self.object_info_label.setStyleSheet("padding: 8px; color: #black;")
        self.stats_dock = QDockWidget("Информация об объекте", self)
        self.stats_dock.setWidget(self.object_info_label)
        # Разрешаем располагать док в правой и нижней областях
        self.stats_dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)
        # По умолчанию док скрыт до выбора объекта
        self.stats_dock.hide()
        # Добавляем док в нижнюю область, чтобы располагался внизу окна
        self.addDockWidget(Qt.BottomDockWidgetArea, self.stats_dock)

        # Панель инструментов
        self._make_toolbar()

        # Статус-бар
        self.status = self.statusBar()
        self._user_label = QLabel(f"Пользователь: {self.user['username']} ({'Администратор' if self.user['role'] == 'admin' else 'Оператор'})")
        self.status.addPermanentWidget(self._user_label)

        # Сигналы
        self.training_view.finished.connect(self.on_training_finished)

    def _make_toolbar(self):
        tb = QToolBar("Действия")
        tb.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, tb)

        act_training = QAction("Тренировка", self)
        act_training.triggered.connect(lambda: self.stack.setCurrentWidget(self.training_view))

        act_profile = QAction("Профиль", self)
        act_profile.triggered.connect(lambda: [
            self.profile_view.reload_history(),
            self.stack.setCurrentWidget(self.profile_view)
        ])

        act_settings = QAction("Настройки", self)
        act_settings.triggered.connect(lambda: self.stack.setCurrentWidget(self.settings_view))

        act_start = QAction("Старт", self)
        act_start.triggered.connect(self.training_view.open_settings)

        act_stop = QAction("Стоп", self)
        act_stop.triggered.connect(self.training_view.end_session)

        act_screenshot = QAction("Скриншот...", self)
        act_screenshot.triggered.connect(self.take_screenshot)

        act_exit = QAction("Выход", self)
        act_exit.triggered.connect(self.close)

        tb.addAction(act_training)
        tb.addAction(act_profile)
        tb.addAction(act_settings)
        tb.addSeparator()
        tb.addAction(act_start)
        tb.addAction(act_stop)
        tb.addSeparator()
        tb.addAction(act_screenshot)
        tb.addSeparator()
        tb.addAction(act_exit)

    def add_notification(self, message: str, screenshot: str = None, type_: str = "info"):
        self.notifications.add(message)
        try:
            self.db.add_event(self.user["id"], type_, message, screenshot)
        except Exception:
            pass  # не мешаем работе из-за ошибок логирования

    def on_training_finished(self, correct, wrong, started_at_iso, duration_sec):
        try:
            self.db.add_training(self.user["id"], started_at_iso, duration_sec, correct, wrong)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка сохранения", f"Не удалось сохранить результаты: {e}")
        self.profile_view.reload_history()
        self.add_notification(f"Итоги сеанса: верно={correct}, ошибки={wrong}, длительность={duration_sec} сек")

    def show_object_info(self, obj):
        """
        Показывает информацию о выбранном объекте в отдельном доке. Если объект
        None, скрывает док. Вызывается из TrainingView при клике на объект.
        """
        if not obj:
            self.hide_object_info()
            return
        # Получаем текст статистики от объекта; используем try/except на случай
        # необычных исключений
        try:
            text = obj.get_stats_text()
        except Exception:
            text = ""
        self.object_info_label.setText(text)
        self.stats_dock.show()

    def update_object_info(self, obj):
        """
        Обновляет текст в доке статистики для текущего объекта. Метод ничего
        не делает, если док скрыт или объект пуст.
        """
        if not obj or not self.stats_dock.isVisible():
            return
        try:
            text = obj.get_stats_text()
        except Exception:
            text = ""
        self.object_info_label.setText(text)

    def hide_object_info(self):
        """
        Скрывает док с информацией об объекте и очищает текст.
        """
        try:
            self.stats_dock.hide()
            self.object_info_label.setText("")
        except Exception:
            pass

    def take_screenshot(self):
        try:
            name = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            path, _ = QFileDialog.getSaveFileName(self, "Сохранить скриншот", name, "PNG (*.png)")
            if path:
                pix = self.grab()
                pix.save(path)
                self.add_notification(f"Скриншот сохранён: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить скриншот: {e}")

    def closeEvent(self, event):
        # Закрываем БД при выходе
        try:
            self.db.close()
        except Exception:
            pass
        event.accept()


def main():
        app = QApplication(sys.argv)
        db = DB()
        login = LoginDialog(db)
        user = login.get_user()
        if not user:
            sys.exit(0)

        win = MainWindow(db, user)
        win.show()
        sys.exit(app.exec_())

if __name__ == "__main__":
    main()
