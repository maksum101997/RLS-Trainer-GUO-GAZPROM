import os
import math
import time
import random
from datetime import datetime

from PyQt5.QtCore import Qt, QPointF, QRectF, QLineF, pyqtSignal
from PyQt5.QtGui import (
    QBrush, QPen, QColor, QTransform, QPolygonF, QPainterPath, QPixmap, QPainter
)
from PyQt5.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsEllipseItem, QGraphicsPathItem,
    QGraphicsPolygonItem, QGraphicsLineItem, QGraphicsPathItem as _QGraphicsPathItem,
    QGraphicsPixmapItem, QGraphicsItem
)

# Папки/пути
SCREENSHOTS_DIR = "screenshots"

# Мир и отрисовка
WORLD_WIDTH = 20000
WORLD_HEIGHT = 20000

# EDIT HERE: путь к файлу карты (файл в assets/)
DEFAULT_MAP_PATH = "assets/spb.map.png"

# Лимиты и параметры
MAX_TRAJ_POINTS = 400
DEFAULT_MAX_OBJECTS = 20

# EDIT HERE: координаты центра радара на сцене (в единицах сцены/пикселях)
DEFAULT_RADAR_CENTER = QPointF(2000, 0)


def point_in_polygon(point: QPointF, polygon: QPolygonF) -> bool:
    x, y = point.x(), point.y()
    inside = False
    n = polygon.count()
    for i in range(n):
        p1 = polygon[i]
        p2 = polygon[(i + 1) % n]
        if ((p1.y() > y) != (p2.y() > y)) and \
           (x < (p2.x() - p1.x()) * (y - p1.y()) / (p2.y() - p1.y() + 1e-9) + p1.x()):
            inside = not inside
    return inside


class ZoneItem(QGraphicsPolygonItem):
    def __init__(self, polygon: QPolygonF, zone_type="detect"):
        super().__init__(polygon)
        self.zone_type = zone_type
        if zone_type == "detect":
            pen = QPen(QColor(0, 180, 0, 160), 2, Qt.DashLine)
            self.setBrush(QBrush(QColor(0, 255, 0, 40)))
        else:
            pen = QPen(QColor(180, 0, 0, 160), 2, Qt.DashLine)
            self.setBrush(QBrush(QColor(255, 0, 0, 40)))
        self.setPen(pen)
        self.base_pen = pen
        self.hover_pen = QPen(pen.color().lighter(120), max(2, pen.width()), Qt.DashLine)
        self.selected_pen = QPen(QColor(255, 255, 255, 220), max(3, pen.width()+1), Qt.SolidLine)

        self.setZValue(-5)
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsFocusable)
        self.setAcceptHoverEvents(True)

    def hoverEnterEvent(self, event):
        self.setPen(self.hover_pen)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setPen(self.selected_pen if self.isSelected() else self.base_pen)
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.setPen(self.selected_pen if value else self.base_pen)
        return super().itemChange(change, value)


class TrajectoryItem(QGraphicsPathItem):
    def __init__(self, color=QColor(0, 0, 255)):
        super().__init__()
        pen = QPen(color, 36, Qt.DotLine)
        self.setPen(pen)
        self.setZValue(-1)


class HeadingItem(QGraphicsLineItem):
    def __init__(self):
        super().__init__()
        pen = QPen(QColor(255, 255, 0), 2)
        self.setPen(pen)
        self.setZValue(1)


class MovingObjectItem(QGraphicsEllipseItem):
    _uid_counter = 1

    def __init__(self, type_, pos: QPointF, velocity: QPointF, speed_mps: float,
                 show_traj=True, show_heading=True):
        r = 45  # Радиус объекта (можно изменить по желанию)
        super().__init__(-r, -r, 2*r, 2*r)  # Создание круга

        self.uid = MovingObjectItem._uid_counter
        MovingObjectItem._uid_counter += 1

        self.setPos(pos)
        self.type_ = type_  # Сохраняем тип объекта (для логики)
        self.velocity = velocity
        self.speed_mps = speed_mps
        self.spawn_time = time.time()
        self.traj_points = [pos]
        self.traj_item = TrajectoryItem()
        self.heading_item = HeadingItem()
        self.show_traj = show_traj
        self.show_heading = show_heading

        # [state] — состояние объекта
        self.state = "normal"  # Статусы: normal | suppressed | landed
        self.label = None
        self.confidence = 0.0

        # [ECM] — элементы помех
        self.has_ecm = False
        self.ecm_item = QGraphicsEllipseItem(-14, -14, 28, 28, self)
        self.ecm_item.setZValue(4)
        self.ecm_item.setPen(QPen(QColor(0, 120, 255, 200), 2, Qt.SolidLine))
        self.ecm_item.setBrush(QBrush(QColor(0, 120, 255, 30)))
        self.ecm_item.setVisible(False)

        # Устанавливаем одинаковый цвет для всех объектов (bvs и bird)
        self.setBrush(QBrush(QColor(0, 200, 255)))  # Голубой цвет для всех объектов
        self.setPen(QPen(QColor(0, 120, 180), 1))   # Темно-голубая обводка

        self.setAcceptHoverEvents(True)
        self.setZValue(5)

        # Индикатор последней зоны колец (-1 = вне)
        self._ring_band_last = -1

    def lifetime(self):
        return time.time() - self.spawn_time

    def _update_visuals(self):
        # Логика изменения внешнего вида объекта
        if self.state == "suppressed":
            self.setBrush(QBrush(QColor(150, 150, 150)))  # Цвет при подавлении
            self.setPen(QPen(QColor(90, 90, 90), 1))  # Темная обводка
        elif self.state == "landed":
            self.setBrush(QBrush(QColor(0, 200, 120)))  # Цвет при приземлении
            self.setPen(QPen(QColor(0, 120, 70), 1))  # Зеленая обводка
        else:
            self.setBrush(QBrush(QColor(0, 200, 255)))  # Голубой цвет для обычных объектов
            self.setPen(QPen(QColor(0, 120, 180), 1))  # Темно-голубая обводка

        self.ecm_item.setVisible(self.has_ecm)

    def update_motion(self, dt, map_scene):
        dx = self.velocity.x() * dt
        dy = self.velocity.y() * dt
        new_pos = self.pos() + QPointF(dx, dy)

        if self.type_ == "bird":  # Логика для типа "bird"
            center = map_scene.radar_center
            away = (self.pos() - center)
            dist = math.hypot(away.x(), away.y()) + 1e-6
            away_norm = QPointF(away.x()/dist, away.y()/dist)
            angle = (random.random() - 0.5) * 0.3
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            vx, vy = self.velocity.x(), self.velocity.y()
            self.velocity = QPointF(vx*cos_a - vy*sin_a, vx*sin_a + vy*cos_a)
            self.velocity = self.velocity * 0.8 + away_norm * (0.2 * self.speed_mps)

            vlen = math.hypot(self.velocity.x(), self.velocity.y())
            if vlen > 1e-6:
                self.velocity = QPointF(self.velocity.x()/vlen * self.speed_mps,
                                        self.velocity.y()/vlen * self.speed_mps)
            dx = self.velocity.x() * dt
            dy = self.velocity.y() * dt
            new_pos = self.pos() + QPointF(dx, dy)

        self.setPos(new_pos)

        # Обновляем траекторию
        if self.show_traj:
            self.traj_points.append(new_pos)
            if len(self.traj_points) > MAX_TRAJ_POINTS:
                self.traj_points = self.traj_points[-MAX_TRAJ_POINTS:]
            path = QPainterPath(self.traj_points[0])
            for p in self.traj_points[1:]:
                path.lineTo(p)
            self.traj_item.setPath(path)

        # Обновляем направление
        if self.show_heading:
            v = self.velocity
            vlen = math.hypot(v.x(), v.y())
            if vlen > 1e-9:
                dir_norm = QPointF(v.x()/vlen, v.y()/vlen)
                start = new_pos
                end = new_pos + dir_norm * 30.0
                self.heading_item.setLine(QLineF(start, end))

        # Удаляем объект по времени жизни
        if self.type_ == "bird" and getattr(map_scene, "bird_lifetime_limit", None) is not None:
            if self.lifetime() > map_scene.bird_lifetime_limit:
                map_scene.remove_object(self)
                return

        # Ограничение по дальности
        limit = getattr(map_scene, "object_range_limit", 9000.0)
        if limit is not None:
            cx, cy = map_scene.radar_center.x(), map_scene.radar_center.y()
            if math.hypot(new_pos.x() - cx, new_pos.y() - cy) > float(limit):
                map_scene.remove_object(self)
                return

        self._update_visuals()

    def hoverEnterEvent(self, event):
        self.update_tooltip()
        super().hoverEnterEvent(event)

    def hoverMoveEvent(self, event):
        self.update_tooltip()
        super().hoverMoveEvent(event)

    def update_tooltip(self):
        lon = self.pos().x()
        lat = self.pos().y()
        spd = self.speed_mps
        lbl = self.label or "-"
        conf = f"{self.confidence:.2f}" if self.label else "-"
        self.setToolTip(
        
            f"Скорость: {spd:.1f} м/с\n"
            f"Долгота: {lon:.1f}\nШирота: {lat:.1f}\n"
            f"Состояние: {self.state}\n"
        )

class MapScene(QGraphicsScene):
    alarmTriggered = pyqtSignal(str)
    ringEvent = pyqtSignal(int, int, float)  # uid, band_index, distance_m

    def __init__(self, db, show_traj=True, show_heading=True,
                 max_objects_limit=DEFAULT_MAX_OBJECTS,
                 map_path: str = DEFAULT_MAP_PATH,
                 radar_center: QPointF = DEFAULT_RADAR_CENTER,
                 mode: str = "training"):  # 🔧 [mode] добавлен параметр режима
        super().__init__()
        self.db = db
        self.show_traj = show_traj
        self.show_heading = show_heading
        self.max_objects_limit = max_objects_limit
        self.objects = []
        self.detect_zones = []
        self.ignore_zones = []
        self.radar_center = QPointF(radar_center)

        # Управление авто-удалением объектов
        self.bird_lifetime_limit = 10.0
        self.object_range_limit = 9000.0

        # 🔧 [mode] режим сцены: training | live
        self.mode = mode

        self.map_item = None
        self._init_map_background(map_path)
        self._init_radar_rings()

        self.drawing_mode = None
        self.temp_polygon = None
        self.temp_points = []

        # Радиусы колец (м)
        self.ring_radii = [1000, 3000, 7000]

    def _init_map_background(self, map_path: str):
        self.setSceneRect(QRectF(-WORLD_WIDTH/2, -WORLD_HEIGHT/2, WORLD_WIDTH, WORLD_HEIGHT))
        self.setBackgroundBrush(QBrush(QColor(12, 26, 32)))

        try:
            if map_path and os.path.exists(map_path):
                pm = QPixmap(map_path)
                if not pm.isNull():
                    self.map_item = QGraphicsPixmapItem(pm)
                    sx = WORLD_WIDTH / pm.width()
                    sy = WORLD_HEIGHT / pm.height()
                    transform = QTransform()
                    transform.scale(sx, sy)
                    self.map_item.setTransform(transform)
                    self.map_item.setPos(-WORLD_WIDTH/2, -WORLD_HEIGHT/2)
                    self.map_item.setZValue(-100)
                    self.addItem(self.map_item)
            else:
                print(f"[graphics] Map file not found: {map_path}")
        except Exception as e:
            print(f"[graphics] Failed to load map: {e}")

    def _init_radar_rings(self):
        center = self.radar_center
        for item in list(self.items()):
            if isinstance(item, (QGraphicsEllipseItem, QGraphicsLineItem)) and item.zValue() <= -9:
                self.removeItem(item)

        for dist, color, z in [(1000, QColor(0, 80, 160, 90), -10),
                               (3000, QColor(0, 60, 120, 60), -11),
                               (7000, QColor(0, 40, 80, 40), -12)]:
            ring = self.addEllipse(QRectF(center.x() - dist, center.y() - dist, 2*dist, 2*dist),
                                   QPen(QColor(0, 180, 240, 120), 1, Qt.SolidLine),
                                   QBrush(color))
            ring.setZValue(z)

        axis_pen = QPen(QColor(50, 90, 110, 180), 1, Qt.DashDotLine)
        self.addLine(center.x() - 7500, center.y(), center.x() + 7500, center.y(), axis_pen).setZValue(-9)
        self.addLine(center.x(), center.y() - 7500, center.x(), center.y() + 7500, axis_pen).setZValue(-9)

    def set_radar_center(self, point: QPointF, redraw=True):
        self.radar_center = QPointF(point)
        if redraw:
            self._init_radar_rings()

    def add_object(self, item: MovingObjectItem):
        self.addItem(item.traj_item)
        self.addItem(item.heading_item)
        self.addItem(item)
        self.objects.append(item)

    def remove_object(self, item: MovingObjectItem):
        try:
            self.removeItem(item.traj_item)
            self.removeItem(item.heading_item)
            self.removeItem(item)
            self.objects.remove(item)
        except ValueError:
            pass

    def set_show_flags(self, show_traj, show_heading):
        self.show_traj = show_traj
        self.show_heading = show_heading
        for obj in self.objects:
            obj.show_traj = show_traj
            obj.show_heading = show_heading
            if not show_traj:
                obj.traj_item.setPath(QPainterPath())
            if not show_heading:
                obj.heading_item.setLine(QLineF())

    def start_draw_zone(self, zone_type):
        self.cancel_temp_zone()
        self.drawing_mode = zone_type
        self.temp_points = []
        self.temp_polygon = _QGraphicsPathItem()
        pen = QPen(QColor(120, 220, 120) if zone_type == "detect" else QColor(220, 120, 120))
        pen.setStyle(Qt.DashLine)
        self.temp_polygon.setPen(pen)
        self.temp_polygon.setZValue(-2)
        self.addItem(self.temp_polygon)

    def cancel_temp_zone(self):
        if self.temp_polygon:
            self.removeItem(self.temp_polygon)
        self.temp_polygon = None
        self.temp_points = []
        self.drawing_mode = None

    def finalize_zone(self):
        if len(self.temp_points) >= 3 and self.drawing_mode:
            poly = QPolygonF(self.temp_points)
            item = ZoneItem(poly, self.drawing_mode)
            self.addItem(item)
            if self.drawing_mode == "detect":
                self.detect_zones.append(item)
            else:
                self.ignore_zones.append(item)
        self.cancel_temp_zone()

    def mousePressEvent(self, event):
        if self.drawing_mode and event.button() == Qt.LeftButton:
            self.temp_points.append(event.scenePos())
            self._update_temp_path()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.drawing_mode and event.button() == Qt.RightButton:
            self.finalize_zone()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self.drawing_mode and self.temp_points:
            pts = self.temp_points + [event.scenePos()]
            self._update_temp_path(pts)
            return
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.scenePos(), QTransform())
        if isinstance(item, ZoneItem):
            self.remove_zone_item(item)
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            self.delete_selected_zones()
            return
        if event.key() == Qt.Key_Escape and self.drawing_mode:
            self.cancel_temp_zone()
            return
        super().keyPressEvent(event)

    def delete_selected_zones(self):
        for item in list(self.selectedItems()):
            if isinstance(item, ZoneItem):
                self.remove_zone_item(item)

    def remove_zone_item(self, item: ZoneItem):
        if item in self.detect_zones:
            self.detect_zones.remove(item)
        if item in self.ignore_zones:
            self.ignore_zones.remove(item)
        self.removeItem(item)

    def _update_temp_path(self, pts=None):
        pts = pts or self.temp_points
        if not pts:
            return
        path = QPainterPath(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        self.temp_polygon.setPath(path)

    def is_in_detect_but_not_ignored(self, pos: QPointF) -> bool:
        in_detect = False
        for z in self.detect_zones:
            if point_in_polygon(pos, z.polygon()):
                in_detect = True
                break
        if not in_detect:
            return False
        for z in self.ignore_zones:
            if point_in_polygon(pos, z.polygon()):
                return False
        return True

    def _ring_band_for_dist(self, dist: float) -> int:
        for i, r in enumerate(self.ring_radii):
            if dist <= r:
                return i
        return -1

    def tick(self, dt, parent_window):
        to_check_alarm = []
        for obj in list(self.objects):
            obj.update_motion(dt, self)
            to_check_alarm.append(obj)

        for obj in to_check_alarm:
            # кольца
            cx, cy = self.radar_center.x(), self.radar_center.y()
            dist = math.hypot(obj.pos().x() - cx, obj.pos().y() - cy)
            band_now = self._ring_band_for_dist(dist)
            if band_now != obj._ring_band_last and band_now != -1:
                obj._ring_band_last = band_now
                self.ringEvent.emit(obj.uid, band_now, dist)
            else:
                obj._ring_band_last = band_now

            # зоны обнаружения
            if obj.type_ == "bvs":
                if self.is_in_detect_but_not_ignored(obj.pos()):
                    self.classify_object(obj)
                    if self.mode == "training":
                        self.raise_alarm(parent_window, f"БВС в зоне обнаружения! ({obj.pos().x():.0f}, {obj.pos().y():.0f})")
                    else:
                        self.raise_alarm(parent_window, f"БВС в зоне обнаружения! ({obj.pos().x():.0f}, {obj.pos().y():.0f})")
                    self.remove_object(obj)

    def raise_alarm(self, parent_window, message: str):
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
        shot_path = os.path.join(SCREENSHOTS_DIR, f"alarm_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        if hasattr(parent_window, "training_view"):
            pv = parent_window.training_view.map_view.viewport() if hasattr(parent_window.training_view, "map_view") else parent_window.training_view
            pix = pv.grab()
        else:
            pix = parent_window.grab()
        try:
            pix.save(shot_path)
        except Exception:
            shot_path = None
        parent_window.add_notification(message, screenshot=shot_path)

    def spawn_random_object(self, bvs_ratio=0.5):
        if len(self.objects) >= self.max_objects_limit:
            return

        cx, cy = self.radar_center.x(), self.radar_center.y()
        type_ = "bvs" if random.random() < bvs_ratio else "bird"

        if type_ == "bvs":
            r = random.uniform(3000, 7000)
            ang = random.uniform(0, 2*math.pi)
            dx = math.cos(ang) * r
            dy = math.sin(ang) * r
            x = cx + dx
            y = cy + dy
            speed = random.uniform(25, 35)
            v = QPointF(-dx, -dy)
            vlen = math.hypot(v.x(), v.y())
            v = QPointF(v.x()/vlen * speed, v.y()/vlen * speed)
        else:
            r = random.uniform(100, 7000)
            ang = random.uniform(0, 2*math.pi)
            dx = math.cos(ang) * r
            dy = math.sin(ang) * r
            x = cx + dx
            y = cy + dy
            speed = random.uniform(2, 10)
            away = QPointF(dx, dy)
            alen = math.hypot(away.x(), away.y())
            v = QPointF(away.x()/alen * speed, away.y()/alen * speed)
            a = random.uniform(-0.6, 0.6)
            cos_a, sin_a = math.cos(a), math.sin(a)
            v = QPointF(v.x()*cos_a - v.y()*sin_a, v.x()*sin_a + v.y()*cos_a)

        obj = MovingObjectItem(type_, QPointF(x, y), v, speed, self.show_traj, self.show_heading)
        self.add_object(obj)

    def pick_object_at(self, scene_pos: QPointF, pixel_radius=10, view=None):
        if view is None:
            return None
        best = None
        best_dist_px = 1e9
        for obj in self.objects:
            pt_view = view.mapFromScene(obj.pos())
            click_view = view.mapFromScene(scene_pos)
            dist_px = math.hypot(pt_view.x() - click_view.x(), pt_view.y() - click_view.y())
            if dist_px < pixel_radius and dist_px < best_dist_px:
                best = obj
                best_dist_px = dist_px
        return best

    # 🔧 [actions]
    def suppress_object(self, obj: MovingObjectItem):
        obj.state = "suppressed"
        obj._update_visuals()

    def land_object(self, obj: MovingObjectItem):
        obj.state = "landed"
        obj._update_visuals()

    def toggle_ecm(self, obj: MovingObjectItem, enabled: bool = True):
        obj.has_ecm = enabled
        obj._update_visuals()

    def classify_object(self, obj: MovingObjectItem):
        obj.label, obj.confidence = classifier(
            calculate_speed(obj),
            calculate_course(obj),
            obj.lifetime()
        )

    # 🔧 snapshot для веб-карты
    def objects_snapshot(self):
        data = []
        for o in self.objects:
            data.append({
                "uid": o.uid,
                "type": o.type_,
                "x": float(o.pos().x()),
                "y": float(o.pos().y()),
                "speed": float(o.speed_mps),
                "course": float(calculate_course(o))
            })
        return data


class MapView(QGraphicsView):
    targetIdentified = pyqtSignal(bool)

    def __init__(self, scene: MapScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(self.renderHints() | QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.setBackgroundBrush(QBrush(QColor(10, 20, 26)))

    def wheelEvent(self, event):
        angle = event.angleDelta().y()
        factor = 1.15 if angle > 0 else 1/1.15
        self.scale(factor, factor)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            obj = self.scene().pick_object_at(scene_pos, pixel_radius=14, view=self)
            if obj:
                correct = (obj.type_ == "bvs")
                self.targetIdentified.emit(correct)
                self.scene().remove_object(obj)
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Escape):
            self.scene().keyPressEvent(event)
            return
        super().keyPressEvent(event)

    def reset_to_home(self, db):
        s = db.get_settings()
        if not s:
            return
        self.setTransform(QTransform())
        scale = s["home_scale"] if s["home_scale"] else 1.0
        self.scale(scale, scale)
        center = QPointF(s["home_x"] or 0.0, s["home_y"] or 0.0)
        self.centerOn(center)

    def north_up(self):
        t = self.transform()
        scale_x = math.hypot(t.m11(), t.m12())
        scale_y = math.hypot(t.m21(), t.m22())
        center = self.mapToScene(self.viewport().rect().center())
        self.setTransform(QTransform())
        self.scale(scale_x, scale_y)
        self.centerOn(center)


# 🔧 [math] Вспомогательные функции для классификации
def calculate_speed(obj: MovingObjectItem) -> float:
    return float(obj.speed_mps)

def calculate_course(obj: MovingObjectItem) -> float:
    ang = math.degrees(math.atan2(obj.velocity.y(), obj.velocity.x()))
    if ang < 0:
        ang += 360.0
    return ang

def classifier(speed: float, course: float, time_alive: float):
    if speed > 15.0 and time_alive < 60.0:
        return "bvs", 0.8
    return "bird", 0.85
