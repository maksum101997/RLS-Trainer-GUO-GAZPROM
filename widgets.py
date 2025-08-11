from PyQt5.QtWidgets import QDockWidget, QListWidget
from PyQt5.QtCore import Qt
from datetime import datetime


class NotificationsDock(QDockWidget):
    def __init__(self, parent=None):
        super().__init__("Центр уведомлений", parent)
        self.list = QListWidget()
        self.setWidget(self.list)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

    def add(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.list.addItem(f"[{timestamp}] {message}")
        self.list.scrollToBottom()
