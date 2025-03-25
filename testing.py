import asyncio
from bleak import BleakScanner, BleakClient
import sys
import logging
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QPushButton, QVBoxLayout, QWidget, QListWidget,
    QMessageBox, QCheckBox, QColorDialog, QFileDialog, QDialog, QSpinBox, QLineEdit,
    QHBoxLayout, QGridLayout, QTabWidget, QGroupBox, QTextEdit, QGraphicsView, QGraphicsScene, QProgressDialog
)
from PyQt5.QtCore import Qt, QTimer, QEvent, QDateTime, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap, QFont, QImage, QIcon
import csv
from datetime import datetime
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from mpl_toolkits.mplot3d import Axes3D
import numpy as np
import winsound
import os
import threading
import json
from qasync import QEventLoop, asyncSlot, asyncClose
from threading import Lock, RLock
from typing import Dict, Any, Optional, List, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('health_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Defined UUIDs (matching those in the ESP32 code)
SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
ACCEL_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
GYRO_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a9"
SPO2_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26aa"
HEART_RATE_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26ab"
TEMP_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26ac"
HEARTTEMP_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26af"  # UUID for heart temperature
PEDOMETER_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26b0"  # UUID for pedometer

class SensorDataManager:
    def __init__(self):
        self.lock = RLock()  # Reentrant lock for thread-safe operations
        self._accel_data = "N/A"
        self._gyro_data = "N/A"
        self._spo2_data = "N/A"
        self._heart_rate_data = "N/A"
        self._temp_data = "N/A"
        self._hearttemp_data = "N/A"
        self._pedometer_data = "N/A"

        self.visible_sensors = {
            "accel": True,
            "gyro": True,
            "spo2": True,
            "heart_rate": True,
            "temp": True,
            "hearttemp": True,
            "pedometer": True
        }

        self.graph_colors = {
            "temp": "blue",
            "hearttemp": "red",
            "hr": "green",
            "spo2": "purple"
        }

        self.alarm_thresholds = {
            "spo2": 90,
            "heart_rate_low": 60,
            "heart_rate_high": 100
        }

        self.running = True
        self.LOG_FILE = os.path.join(os.path.expanduser("~"), "sensor_data.csv")
        self.PROGRAM_VERSION = "1.1.0"
        self.ble_connected = False
        self.last_log_time = None
        self.graph_data_points = 100  # Default number of data points to display

        # Initialize calibration biases
        self.accel_bias = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.gyro_bias = {"x": 0.0, "y": 0.0, "z": 0.0}
        
        # Load calibration from file
        self.load_calibration()

    # Property getters with thread-safe access
    @property
    def accel_data(self):
        with self.lock:
            return self._accel_data

    @property
    def gyro_data(self):
        with self.lock:
            return self._gyro_data

    @property
    def spo2_data(self):
        with self.lock:
            return self._spo2_data

    @property
    def heart_rate_data(self):
        with self.lock:
            return self._heart_rate_data

    @property
    def temp_data(self):
        with self.lock:
            return self._temp_data

    @property
    def hearttemp_data(self):
        with self.lock:
            return self._hearttemp_data

    @property
    def pedometer_data(self):
        with self.lock:
            return self._pedometer_data

    def load_calibration(self):
        """Load calibration biases from a file with error handling."""
        try:
            with open("calibration.json", "r") as f:
                calibration = json.load(f)
                with self.lock:
                    self.accel_bias = calibration.get("accel_bias", {"x": 0.0, "y": 0.0, "z": 0.0})
                    self.gyro_bias = calibration.get("gyro_bias", {"x": 0.0, "y": 0.0, "z": 0.0})
            logger.info("Calibration data loaded successfully")
        except FileNotFoundError:
            logger.warning("No calibration file found. Using default biases.")
        except json.JSONDecodeError:
            logger.error("Invalid calibration file format. Using default biases.")
        except Exception as e:
            logger.error(f"Error loading calibration: {str(e)}")

    def save_calibration(self):
        """Save calibration biases to a file with error handling."""
        try:
            with open("calibration.json", "w") as f:
                with self.lock:
                    json.dump({
                        "accel_bias": self.accel_bias,
                        "gyro_bias": self.gyro_bias
                    }, f, indent=4)
            logger.info("Calibration data saved successfully")
        except Exception as e:
            logger.error(f"Error saving calibration: {str(e)}")
            raise

    def log_data(self, timestamp: str, accel: str, gyro: str, spo2: str, 
                heart_rate: str, temp: str, hearttemp: str) -> None:
        """Log sensor data to a CSV file once per second with error handling."""
        if self.last_log_time is None or (datetime.now() - self.last_log_time).total_seconds() >= 1:
            try:
                file_exists = os.path.exists(self.LOG_FILE)
                with open(self.LOG_FILE, mode="a", newline="") as file:
                    writer = csv.writer(file)
                    if not file_exists or os.path.getsize(self.LOG_FILE) == 0:
                        writer.writerow(["Timestamp", "Accelerometer", "Gyroscope", 
                                       "SpO2", "Heart Rate", "Temperature", "Heart Temperature"])
                    writer.writerow([timestamp, accel, gyro, spo2, heart_rate, temp, hearttemp])
                self.last_log_time = datetime.now()
            except PermissionError:
                logger.error(f"Permission denied when writing to {self.LOG_FILE}")
            except Exception as e:
                logger.error(f"Error logging data: {str(e)}")

    def play_sound(self, filename: str) -> None:
        """Play a sound file with platform-specific handling and error checking."""
        if not os.path.exists(filename):
            logger.warning(f"Sound file '{filename}' not found.")
            return

        try:
            if os.name == "nt":  # Windows
                winsound.PlaySound(filename, winsound.SND_ASYNC | winsound.SND_FILENAME)
            else:  # macOS/Linux
                os.system(f"afplay {filename} &" if sys.platform == 'darwin' else f"aplay {filename} &")
        except Exception as e:
            logger.error(f"Error playing sound: {str(e)}")

    def update_sensor_data(self, sensor_type: str, data: bytes) -> None:
        """Update sensor data in a thread-safe manner with validation."""
        try:
            value = data.decode("utf-8").strip()
            if not value:
                logger.warning(f"Empty data received for {sensor_type}")
                return

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            with self.lock:
                if sensor_type == "accel":
                    x, y, z = value.split(',')
                    self._accel_data = f"X: {x}, Y: {y}, Z: {z}"
                elif sensor_type == "gyro":
                    x, y, z = value.split(',')
                    self._gyro_data = f"X: {x}, Y: {y}, Z: {z}"
                elif sensor_type == "spo2":
                    self._spo2_data = value
                elif sensor_type == "heart_rate":
                    self._heart_rate_data = value
                elif sensor_type == "temp":
                    self._temp_data = value
                elif sensor_type == "hearttemp":
                    self._hearttemp_data = value
                elif sensor_type == "pedometer":
                    self._pedometer_data = value

                # Log all data
                self.log_data(timestamp, self._accel_data, self._gyro_data, 
                            self._spo2_data, self._heart_rate_data, 
                            self._temp_data, self._hearttemp_data)

                # Check for alarms
                self._check_alarms()

        except ValueError as e:
            logger.error(f"Invalid data format for {sensor_type}: {value}. Error: {str(e)}")
        except Exception as e:
            logger.error(f"Error updating {sensor_type} data: {str(e)}")

    def _check_alarms(self) -> None:
        """Check sensor values against thresholds and trigger alarms if needed."""
        try:
            alarms = []
            
            # Check SpO2
            if self._spo2_data != "N/A":
                spo2 = float(self._spo2_data)
                if spo2 < self.alarm_thresholds["spo2"]:
                    alarms.append("Low SpO2")
            
            # Check heart rate
            if self._heart_rate_data != "N/A":
                hr = float(self._heart_rate_data)
                if hr < self.alarm_thresholds["heart_rate_low"]:
                    alarms.append("Low Heart Rate")
                elif hr > self.alarm_thresholds["heart_rate_high"]:
                    alarms.append("High Heart Rate")
            
            # Trigger alarm if any thresholds are crossed
            if alarms:
                self.play_sound("alarm.wav")
                
        except ValueError:
            logger.warning("Invalid sensor data for alarm checking")
        except Exception as e:
            logger.error(f"Error in alarm checking: {str(e)}")

class SettingsWindow(QDialog):
    def __init__(self, parent=None, data_manager=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.setWindowTitle("Settings")
        self.setWindowFlags(self.windowFlags() | Qt.WindowContextHelpButtonHint)
        self.setStyleSheet("""
            QDialog {
                background: #0B2E33; 
                color: #93B1B5;
            }
            QLabel {
                font-size: 12px;
            }
            QPushButton {
                background-color: #1E4E54;
                color: white;
                border-radius: 5px;
                padding: 5px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #2D5F66;
            }
            QSpinBox {
                background-color: white;
                color: black;
                border: 1px solid #1E4E54;
                padding: 2px;
            }
        """)

        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        """Initialize the UI components."""
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)

        # SpO2 threshold
        self.spo2_threshold = QSpinBox()
        self.spo2_threshold.setRange(0, 100)
        self.spo2_threshold.setSingleStep(1)
        spo2_layout = QHBoxLayout()
        spo2_layout.addWidget(QLabel("SpO2 Alarm Threshold (%):"))
        spo2_layout.addWidget(self.spo2_threshold)
        layout.addLayout(spo2_layout)

        # Heart rate thresholds
        hr_low_layout = QHBoxLayout()
        self.hr_low_threshold = QSpinBox()
        self.hr_low_threshold.setRange(30, 200)
        hr_low_layout.addWidget(QLabel("Low Heart Rate Threshold:"))
        hr_low_layout.addWidget(self.hr_low_threshold)
        
        hr_high_layout = QHBoxLayout()
        self.hr_high_threshold = QSpinBox()
        self.hr_high_threshold.setRange(30, 200)
        hr_high_layout.addWidget(QLabel("High Heart Rate Threshold:"))
        hr_high_layout.addWidget(self.hr_high_threshold)
        
        layout.addLayout(hr_low_layout)
        layout.addLayout(hr_high_layout)

        # CSV path selection
        self.path_label = QLabel(f"Current CSV Path: {self.data_manager.LOG_FILE}")
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)
        
        self.path_button = QPushButton("Select Data Directory")
        self.path_button.clicked.connect(self._select_directory)
        layout.addWidget(self.path_button)

        # Clear data button
        self.clear_button = QPushButton("Clear Data")
        self.clear_button.clicked.connect(self._clear_data)
        layout.addWidget(self.clear_button)

        # Button box
        button_layout = QHBoxLayout()
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self._save_settings)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)
        self.adjustSize()
        self.setFixedSize(self.sizeHint().width() + 50, self.sizeHint().height())

    def _load_settings(self):
        """Load current settings into the UI."""
        with self.data_manager.lock:
            self.spo2_threshold.setValue(self.data_manager.alarm_thresholds["spo2"])
            self.hr_low_threshold.setValue(self.data_manager.alarm_thresholds["heart_rate_low"])
            self.hr_high_threshold.setValue(self.data_manager.alarm_thresholds["heart_rate_high"])

    def _save_settings(self):
        """Save settings from the UI to the data manager."""
        with self.data_manager.lock:
            self.data_manager.alarm_thresholds["spo2"] = self.spo2_threshold.value()
            self.data_manager.alarm_thresholds["heart_rate_low"] = self.hr_low_threshold.value()
            self.data_manager.alarm_thresholds["heart_rate_high"] = self.hr_high_threshold.value()
        
        QMessageBox.information(self, "Success", "Settings saved successfully.")
        self.accept()

    def _select_directory(self):
        """Select a directory for saving the CSV file with validation."""
        path = QFileDialog.getExistingDirectory(
            self, 
            "Select Directory",
            os.path.dirname(self.data_manager.LOG_FILE) if self.data_manager.LOG_FILE else os.path.expanduser("~"))
        
        if path:
            try:
                # Test if we can write to the directory
                test_file = os.path.join(path, "test_write.tmp")
                with open(test_file, "w") as f:
                    f.write("test")
                os.remove(test_file)
                
                self.data_manager.LOG_FILE = os.path.join(path, "sensor_data.csv")
                self.path_label.setText(f"Current CSV Path: {self.data_manager.LOG_FILE}")
                QMessageBox.information(self, "Success", f"Data will be saved to: {self.data_manager.LOG_FILE}")
            except PermissionError:
                QMessageBox.critical(self, "Error", "Cannot write to selected directory. Permission denied.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error selecting directory: {str(e)}")

    def _clear_data(self):
        """Clear saved data with confirmation."""
        reply = QMessageBox.question(
            self, 
            "Confirm Clear", 
            "Are you sure you want to clear all logged data? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                if os.path.exists(self.data_manager.LOG_FILE):
                    os.remove(self.data_manager.LOG_FILE)
                    QMessageBox.information(self, "Success", "Data cleared successfully.")
                else:
                    QMessageBox.information(self, "Info", "No data file found to clear.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to clear data: {str(e)}")

    def event(self, event):
        """Handle help button events."""
        if event.type() == QEvent.EnterWhatsThisMode:
            self._show_help()
            return True
        return super().event(event)

    def _show_help(self):
        """Show help information for the settings window."""
        help_text = """
        <b>Settings Window Help</b><br><br>
        <b>SpO2 Threshold:</b> Set the minimum oxygen saturation level before triggering an alarm.<br>
        <b>Heart Rate Thresholds:</b> Set the minimum and maximum heart rate values before triggering alarms.<br>
        <b>Data Directory:</b> Choose where sensor data will be saved.<br>
        <b>Clear Data:</b> Delete all previously logged sensor data.<br><br>
        Changes are saved when you click the 'Save' button.
        """
        QMessageBox.information(self, "Help", help_text)

class CustomiseWindow(QDialog):
    def __init__(self, parent=None, data_manager=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.setWindowTitle("Customise")
        self.setWindowFlags(self.windowFlags() | Qt.WindowContextHelpButtonHint)
        self.setStyleSheet("""
            QDialog {
                background: #0B2E33; 
                color: #93B1B5;
            }
            QLabel {
                font-size: 12px;
            }
            QPushButton {
                background-color: #1E4E54;
                color: white;
                border-radius: 5px;
                padding: 5px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #2D5F66;
            }
            QSpinBox {
                background-color: white;
                color: black;
                border: 1px solid #1E4E54;
                padding: 2px;
            }
            QCheckBox {
                spacing: 5px;
            }
        """)

        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        """Initialize the UI components."""
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)

        # Sensor visibility section
        layout.addWidget(QLabel("<b>Sensor Visibility</b>"))
        
        self.visibility_grid = QGridLayout()
        self.visibility_grid.setSpacing(10)
        self.checkboxes = {}
        
        sensors = list(self.data_manager.visible_sensors.keys())
        for i, sensor in enumerate(sensors):
            row = i // 2
            col = i % 2
            cb = QCheckBox(sensor.replace("_", " ").title())
            self.checkboxes[sensor] = cb
            self.visibility_grid.addWidget(cb, row, col)
        
        layout.addLayout(self.visibility_grid)

        # Data points section
        layout.addWidget(QLabel("<b>Graph Settings</b>"))
        
        points_layout = QHBoxLayout()
        points_layout.addWidget(QLabel("Data Points to Display:"))
        self.data_points_spinbox = QSpinBox()
        self.data_points_spinbox.setRange(10, 1000)
        self.data_points_spinbox.setSingleStep(10)
        points_layout.addWidget(self.data_points_spinbox)
        layout.addLayout(points_layout)

        # Color selection section
        layout.addWidget(QLabel("Graph Colors:"))
        
        self.color_buttons = {}
        color_grid = QGridLayout()
        color_grid.setSpacing(10)
        
        for i, (graph, color) in enumerate(self.data_manager.graph_colors.items()):
            row = i // 2
            col = i % 2
            btn = QPushButton(f"{graph.title()}")
            btn.setStyleSheet(f"background-color: {color};")
            btn.clicked.connect(lambda _, g=graph: self._choose_color(g))
            self.color_buttons[graph] = btn
            color_grid.addWidget(btn, row, col)
        
        layout.addLayout(color_grid)

        # Button box
        button_layout = QHBoxLayout()
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self._apply_settings)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.apply_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)
        self.adjustSize()
        self.setFixedSize(self.sizeHint().width() + 50, self.sizeHint().height())

    def _load_settings(self):
        """Load current settings into the UI."""
        with self.data_manager.lock:
            for sensor, cb in self.checkboxes.items():
                cb.setChecked(self.data_manager.visible_sensors[sensor])
            
            self.data_points_spinbox.setValue(self.data_manager.graph_data_points)
            
            for graph, btn in self.color_buttons.items():
                btn.setStyleSheet(f"background-color: {self.data_manager.graph_colors[graph]};")

    def _apply_settings(self):
        """Apply settings from the UI to the data manager."""
        with self.data_manager.lock:
            for sensor, cb in self.checkboxes.items():
                self.data_manager.visible_sensors[sensor] = cb.isChecked()
            
            self.data_manager.graph_data_points = self.data_points_spinbox.value()
        
        QMessageBox.information(self, "Success", "Customization settings applied.")
        self.accept()

    def _choose_color(self, graph: str):
        """Choose a color for the specified graph."""
        color = QColorDialog.getColor()
        if color.isValid():
            with self.data_manager.lock:
                self.data_manager.graph_colors[graph] = color.name()
            self.color_buttons[graph].setStyleSheet(f"background-color: {color.name()};")

    def event(self, event):
        """Handle help button events."""
        if event.type() == QEvent.EnterWhatsThisMode:
            self._show_help()
            return True
        return super().event(event)

    def _show_help(self):
        """Show help information for the customize window."""
        help_text = """
        <b>Customize Window Help</b><br><br>
        <b>Sensor Visibility:</b> Toggle which sensors are displayed in the main window.<br>
        <b>Data Points:</b> Set how many historical data points are shown on graphs.<br>
        <b>Graph Colors:</b> Click buttons to change the colors of each graph line.<br><br>
        Changes take effect when you click 'Apply'.
        """
        QMessageBox.information(self, "Help", help_text)

class BLEConnectionThread(QThread):
    """Thread for handling BLE connection and data reading."""
    connection_status = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)

    def __init__(self, data_manager, address):
        super().__init__()
        self.data_manager = data_manager
        self.address = address
        self.running = True

    def run(self):
        """Main thread execution."""
        asyncio.run(self._read_ble_data())

    async def _read_ble_data(self):
        """Read data from BLE device."""
        while self.running:
            try:
                async with BleakClient(self.address) as client:
                    logger.info(f"Connected to {self.address}")
                    self.connection_status.emit(True)
                    
                    # Enable notifications for all characteristics
                    await self._enable_notifications(client)
                    
                    # Keep connection alive
                    while self.running:
                        await asyncio.sleep(0.1)
                        
            except Exception as e:
                logger.error(f"BLE connection error: {e}")
                self.connection_status.emit(False)
                self.error_occurred.emit(str(e))
                await asyncio.sleep(5)  # Wait before reconnecting

    async def _enable_notifications(self, client):
        """Enable notifications for all characteristics."""
        await client.start_notify(ACCEL_UUID, lambda _, data: self.data_manager.update_sensor_data("accel", data))
        await client.start_notify(GYRO_UUID, lambda _, data: self.data_manager.update_sensor_data("gyro", data))
        await client.start_notify(SPO2_UUID, lambda _, data: self.data_manager.update_sensor_data("spo2", data))
        await client.start_notify(HEART_RATE_UUID, lambda _, data: self.data_manager.update_sensor_data("heart_rate", data))
        await client.start_notify(TEMP_UUID, lambda _, data: self.data_manager.update_sensor_data("temp", data))
        await client.start_notify(HEARTTEMP_UUID, lambda _, data: self.data_manager.update_sensor_data("hearttemp", data))
        await client.start_notify(PEDOMETER_UUID, lambda _, data: self.data_manager.update_sensor_data("pedometer", data))
        logger.info("Notifications enabled for all characteristics")

    def stop(self):
        """Stop the thread gracefully."""
        self.running = False

class IntroWindow(QMainWindow):
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self.ble_thread = None
        self._setup_ui()

    def _setup_ui(self):
        """Initialize the UI components."""
        self.setWindowTitle("Health Monitoring System")
        self.setGeometry(100, 100, 500, 400)
        self.setStyleSheet("""
            QMainWindow {
                background: #082124;
                color: #CBE896;
            }
            QLabel {
                font-size: 14px;
            }
            QPushButton {
                background-color: #1E4E54;
                color: white;
                border-radius: 10px;
                padding: 10px;
                min-width: 150px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #2D5F66;
            }
            #connect_button {
                background-color: #4CAF50;
            }
            #connect_button:hover {
                background-color: #45a049;
            }
            #settings_button {
                background-color: #008CBA;
            }
            #settings_button:hover {
                background-color: #007B9E;
            }
            #customise_button {
                background-color: #FFA500;
            }
            #customise_button:hover {
                background-color: #FF8C00;
            }
            #start_button {
                background-color: #f44336;
            }
            #start_button:hover {
                background-color: #e53935;
            }
        """)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        layout = QVBoxLayout(self.central_widget)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)

        # Program version label
        self.version_label = QLabel(f"Version: {self.data_manager.PROGRAM_VERSION}")
        self.version_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        layout.addWidget(self.version_label)

        # Main label
        self.main_label = QLabel("Health Monitoring System")
        self.main_label.setFont(QFont("Roboto", 24, QFont.Bold))
        self.main_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.main_label)

        # Buttons
        self.connect_button = QPushButton("Connect to Device")
        self.connect_button.setObjectName("connect_button")
        self.connect_button.clicked.connect(self._open_connect_window)
        layout.addWidget(self.connect_button)

        self.settings_button = QPushButton("Settings")
        self.settings_button.setObjectName("settings_button")
        self.settings_button.clicked.connect(self._open_settings_window)
        layout.addWidget(self.settings_button)

        self.customise_button = QPushButton("Customise")
        self.customise_button.setObjectName("customise_button")
        self.customise_button.clicked.connect(self._open_customise_window)
        layout.addWidget(self.customise_button)

        self.start_button = QPushButton("Start Monitoring")
        self.start_button.setObjectName("start_button")
        self.start_button.clicked.connect(self._start_program)
        layout.addWidget(self.start_button)

        # Connection status
        self.connection_status = QLabel("Device: Not Connected")
        self.connection_status.setFont(QFont("Roboto", 10))
        self.connection_status.setAlignment(Qt.AlignCenter)
        self.connection_status.setStyleSheet("color: #FF6347;" if not self.data_manager.ble_connected else "color: #7CFC00;")
        layout.addWidget(self.connection_status)

        # Help button
        self.help_button = QPushButton("Help")
        self.help_button.clicked.connect(self._show_help)
        layout.addWidget(self.help_button)

    def _open_connect_window(self):
        """Open the device connection window."""
        self.connect_window = QDialog(self)
        self.connect_window.setWindowTitle("Connect to Device")
        self.connect_window.setGeometry(200, 200, 400, 300)
        self.connect_window.setStyleSheet(self.styleSheet())

        layout = QVBoxLayout(self.connect_window)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)

        # Instructions
        instructions = QLabel(
            "1. Click 'Scan for Devices'\n"
            "2. Select your device from the list\n"
            "3. Click 'Connect'\n\n"
            "Ensure your device is powered on and in range."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        # Scan button
        self.scan_button = QPushButton("Scan for Devices")
        self.scan_button.clicked.connect(self._scan_ble_devices)
        layout.addWidget(self.scan_button)

        # Device list
        self.device_list = QListWidget()
        layout.addWidget(self.device_list)

        # Connect button
        self.connect_btn = QPushButton("Connect to Selected Device")
        self.connect_btn.clicked.connect(self._connect_to_device)
        layout.addWidget(self.connect_btn)

        # Status label
        self.scan_status = QLabel("")
        self.scan_status.setWordWrap(True)
        layout.addWidget(self.scan_status)

        self.connect_window.exec_()

    def _scan_ble_devices(self):
        """Scan for BLE devices and update the list."""
        self.scan_status.setText("Scanning for devices...")
        self.device_list.clear()
        self.scan_button.setEnabled(False)

        async def scan():
            try:
                devices = await BleakScanner.discover(timeout=5.0)
                if not devices:
                    self.scan_status.setText("No devices found. Ensure your device is powered on and in range.")
                else:
                    for device in devices:
                        self.device_list.addItem(f"{device.name or 'Unknown'} - {device.address}")
                    self.scan_status.setText(f"Found {len(devices)} devices. Select one to connect.")
            except Exception as e:
                self.scan_status.setText(f"Scan failed: {str(e)}")
            finally:
                self.scan_button.setEnabled(True)

        # Run scan in a separate thread
        threading.Thread(target=asyncio.run, args=(scan(),), daemon=True).start()

    def _connect_to_device(self):
        """Connect to the selected BLE device."""
        selected_item = self.device_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self.connect_window, "Warning", "Please select a device first.")
            return

        device_address = selected_item.text().split(" - ")[-1]
        self.scan_status.setText(f"Connecting to {device_address}...")

        # Stop any existing connection thread
        if self.ble_thread and self.ble_thread.isRunning():
            self.ble_thread.stop()
            self.ble_thread.wait()

        # Start new connection thread
        self.ble_thread = BLEConnectionThread(self.data_manager, device_address)
        self.ble_thread.connection_status.connect(self._update_connection_status)
        self.ble_thread.error_occurred.connect(self._handle_ble_error)
        self.ble_thread.start()

        self.connect_window.close()

    def _update_connection_status(self, connected):
        """Update the connection status display."""
        self.data_manager.ble_connected = connected
        status = "Connected" if connected else "Not Connected"
        color = "#7CFC00" if connected else "#FF6347"
        
        self.connection_status.setText(f"Device: {status}")
        self.connection_status.setStyleSheet(f"color: {color};")
        
        if connected:
            QMessageBox.information(self, "Success", "Device connected successfully!")

    def _handle_ble_error(self, error_msg):
        """Handle BLE connection errors."""
        QMessageBox.critical(self, "Connection Error", f"Failed to connect to device:\n{error_msg}")
        self._update_connection_status(False)

    def _open_settings_window(self):
        """Open the settings window."""
        self.settings_window = SettingsWindow(self, self.data_manager)
        self.settings_window.exec_()

    def _open_customise_window(self):
        """Open the customization window."""
        self.customise_window = CustomiseWindow(self, self.data_manager)
        self.customise_window.exec_()

    def _start_program(self):
        """Start the main monitoring program."""
        if not self.data_manager.ble_connected:
            QMessageBox.critical(self, "Error", "Please connect to a device first!")
            return

        self.close()
        self.main_program = MainProgram(self.data_manager)
        self.main_program.show()

    def _show_help(self):
        """Show help information for the intro window."""
        help_text = """
        <b>Health Monitoring System Help</b><br><br>
        <b>Connect to Device:</b> Scan for and connect to your BLE health monitoring device.<br>
        <b>Settings:</b> Configure alarm thresholds and data storage location.<br>
        <b>Customise:</b> Change which sensors are displayed and their appearance.<br>
        <b>Start Monitoring:</b> Begin viewing real-time health data (requires connected device).<br><br>
        For best results, ensure your device is properly positioned and has good battery life.
        """
        QMessageBox.information(self, "Help", help_text)

    def closeEvent(self, event):
        """Clean up resources when window is closed."""
        if self.ble_thread and self.ble_thread.isRunning():
            self.ble_thread.stop()
            self.ble_thread.wait()
        event.accept()

class MainProgram(QMainWindow):
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self._setup_ui()
        self._setup_sensor_displays()
        self._start_update_timers()

    def _setup_ui(self):
        """Initialize the main UI components."""
        self.setWindowTitle("Health Monitoring Dashboard")
        self.setWindowFlags(self.windowFlags() | Qt.WindowContextHelpButtonHint)
        self.setGeometry(100, 100, 1000, 800)
        self.setStyleSheet("""
            QMainWindow {
                background: #082124;
                color: #CBE896;
            }
            QLabel {
                font-size: 14px;
            }
            QPushButton {
                background-color: #1E4E54;
                color: white;
                border-radius: 5px;
                padding: 5px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #2D5F66;
            }
            QGroupBox {
                border: 1px solid #1E4E54;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
            }
        """)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setSpacing(15)
        self.layout.setContentsMargins(15, 15, 15, 15)

        # Control buttons
        control_layout = QHBoxLayout()
        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self._open_settings_window)
        control_layout.addWidget(self.settings_button)

        self.customise_button = QPushButton("Customise")
        self.customise_button.clicked.connect(self._open_customise_window)
        control_layout.addWidget(self.customise_button)

        self.pop_out_button = QPushButton("Pop-Out Window")
        self.pop_out_button.clicked.connect(self._open_pop_out_window)
        control_layout.addWidget(self.pop_out_button)

        self.return_button = QPushButton("Return to Intro")
        self.return_button.clicked.connect(self._return_to_intro)
        control_layout.addWidget(self.return_button)

        self.layout.addLayout(control_layout)

        # Sensor data display
        self._setup_sensor_displays()

        # Graphs
        self._setup_graph_tabs()

        # Calibration section
        self._setup_calibration()

        # Alarm display
        self.alarm_label = QLabel("No Alerts")
        self.alarm_label.setStyleSheet("font-size: 16px; color: #FF6347;")
        self.alarm_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.alarm_label)

    def _setup_sensor_displays(self):
        """Set up the sensor data display widgets."""
        # Top row sensors
        top_row = QHBoxLayout()
        self.accel_label = self._create_sensor_display("Accelerometer", "N/A")
        self.gyro_label = self._create_sensor_display("Gyroscope", "N/A")
        self.pedometer_label = self._create_sensor_display("Steps Taken", "N/A")
        top_row.addWidget(self.accel_label)
        top_row.addWidget(self.gyro_label)
        top_row.addWidget(self.pedometer_label)
        self.layout.addLayout(top_row)

        # Bottom row sensors
        bottom_row = QHBoxLayout()
        self.heart_rate_label = self._create_sensor_display("Heart Rate", "N/A BPM")
        self.spo2_label = self._create_sensor_display("SpO2", "N/A%")
        self.temp_label = self._create_sensor_display("Temperature", "N/A °C")
        self.hearttemp_label = self._create_sensor_display("Heart Temp", "N/A °C")
        bottom_row.addWidget(self.heart_rate_label)
        bottom_row.addWidget(self.spo2_label)
        bottom_row.addWidget(self.temp_label)
        bottom_row.addWidget(self.hearttemp_label)
        self.layout.addLayout(bottom_row)

    def _create_sensor_display(self, title: str, default_value: str) -> QLabel:
        """Create a standardized sensor display widget."""
        label = QLabel(f"<b>{title}:</b> {default_value}")
        label.setStyleSheet("""
            QLabel {
                border: 1px solid #1E4E54;
                border-radius: 5px;
                padding: 10px;
                background-color: #0B2E33;
                min-width: 200px;
            }
        """)
        label.setAlignment(Qt.AlignCenter)
        return label

    def _setup_graph_tabs(self):
        """Set up the tabbed graph interface."""
        self.tabs = QTabWidget()
        
        # Temperature tab
        temp_tab = QWidget()
        temp_layout = QVBoxLayout(temp_tab)
        self.fig_temp, self.ax_temp = plt.subplots(figsize=(8, 4))
        self._configure_temp_graph()
        self.canvas_temp = FigureCanvas(self.fig_temp)
        temp_layout.addWidget(self.canvas_temp)
        self.tabs.addTab(temp_tab, "Temperature")
        
        # Heart Rate/SpO2 tab
        hr_tab = QWidget()
        hr_layout = QVBoxLayout(hr_tab)
        self.fig_hr, self.ax_hr = plt.subplots(figsize=(8, 4))
        self._configure_hr_graph()
        self.canvas_hr = FigureCanvas(self.fig_hr)
        hr_layout.addWidget(self.canvas_hr)
        self.tabs.addTab(hr_tab, "Heart Rate/SpO2")
        
        # Motion tab
        motion_tab = QWidget()
        motion_layout = QVBoxLayout(motion_tab)
        self.fig_motion, self.ax_motion = plt.subplots(figsize=(8, 4))
        self._configure_motion_graph()
        self.canvas_motion = FigureCanvas(self.fig_motion)
        
        # 3D orientation graph
        self.fig_3d = plt.figure(figsize=(8, 4))
        self.ax_3d = self.fig_3d.add_subplot(111, projection='3d')
        self._configure_3d_graph()
        self.canvas_3d = FigureCanvas(self.fig_3d)
        
        motion_layout.addWidget(self.canvas_motion)
        motion_layout.addWidget(self.canvas_3d)
        self.tabs.addTab(motion_tab, "Motion")
        
        self.layout.addWidget(self.tabs)

    def _configure_temp_graph(self):
        """Configure the temperature graph."""
        self.ax_temp.set_title("Body and Heart Temperature", fontsize=12)
        self.ax_temp.set_xlabel("Time", fontsize=10)
        self.ax_temp.set_ylabel("Temperature (°C)", fontsize=10)
        self.line_temp, = self.ax_temp.plot([], [], lw=2, label="Body Temperature", 
                                          color=self.data_manager.graph_colors["temp"])
        self.line_hearttemp, = self.ax_temp.plot([], [], lw=2, label="Heart Temperature", 
                                               color=self.data_manager.graph_colors["hearttemp"])
        self.ax_temp.legend()
        self.ax_temp.grid(True)
        self._configure_time_axis(self.ax_temp)

    def _configure_hr_graph(self):
        """Configure the heart rate/SpO2 graph."""
        self.ax_hr.set_title("Heart Rate and Oxygen Saturation", fontsize=12)
        self.ax_hr.set_xlabel("Time", fontsize=10)
        self.ax_hr.set_ylabel("Value", fontsize=10)
        self.line_hr, = self.ax_hr.plot([], [], lw=2, label="Heart Rate (BPM)", 
                                      color=self.data_manager.graph_colors["hr"])
        self.line_spo2, = self.ax_hr.plot([], [], lw=2, label="SpO2 (%)", 
                                        color=self.data_manager.graph_colors["spo2"])
        self.ax_hr.legend()
        self.ax_hr.grid(True)
        self._configure_time_axis(self.ax_hr)

    def _configure_motion_graph(self):
        """Configure the motion/acceleration graph."""
        self.ax_motion.set_title("Linear Acceleration", fontsize=12)
        self.ax_motion.set_xlabel("Time", fontsize=10)
        self.ax_motion.set_ylabel("Acceleration (m/s²)", fontsize=10)
        self.line_accel_x, = self.ax_motion.plot([], [], lw=1, label="X", color='r')
        self.line_accel_y, = self.ax_motion.plot([], [], lw=1, label="Y", color='g')
        self.line_accel_z, = self.ax_motion.plot([], [], lw=1, label="Z", color='b')
        self.ax_motion.legend()
        self.ax_motion.grid(True)
        self._configure_time_axis(self.ax_motion)

    def _configure_3d_graph(self):
        """Configure the 3D orientation graph."""
        self.ax_3d.set_title("Device Orientation", fontsize=12)
        self.ax_3d.set_xlabel("X")
        self.ax_3d.set_ylabel("Y")
        self.ax_3d.set_zlabel("Z")
        self.ax_3d.set_xlim(-1, 1)
        self.ax_3d.set_ylim(-1, 1)
        self.ax_3d.set_zlim(-1, 1)
        
        # Initialize arrows for each axis
        self.arrow_x = self.ax_3d.quiver(0, 0, 0, 1, 0, 0, color='r', label='X')
        self.arrow_y = self.ax_3d.quiver(0, 0, 0, 0, 1, 0, color='g', label='Y')
        self.arrow_z = self.ax_3d.quiver(0, 0, 0, 0, 0, 1, color='b', label='Z')
        self.ax_3d.legend()

    def _configure_time_axis(self, ax):
        """Configure time-based axis settings."""
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        ax.xaxis.set_major_locator(mdates.SecondLocator(interval=5))

    def _setup_calibration(self):
        """Set up the calibration controls."""
        calib_group = QGroupBox("Sensor Calibration")
        calib_layout = QHBoxLayout(calib_group)
        
        self.calib_accel_btn = QPushButton("Calibrate Accelerometer")
        self.calib_accel_btn.clicked.connect(self._calibrate_accelerometer)
        calib_layout.addWidget(self.calib_accel_btn)
        
        self.calib_gyro_btn = QPushButton("Calibrate Gyroscope")
        self.calib_gyro_btn.clicked.connect(self._calibrate_gyroscope)
        calib_layout.addWidget(self.calib_gyro_btn)
        
        self.save_calib_btn = QPushButton("Save Calibration")
        self.save_calib_btn.clicked.connect(self._save_calibration)
        calib_layout.addWidget(self.save_calib_btn)
        
        self.layout.addWidget(calib_group)

    def _start_update_timers(self):
        """Start timers for periodic updates."""
        # GUI update (fast)
        self.gui_timer = QTimer()
        self.gui_timer.timeout.connect(self._update_gui)
        self.gui_timer.start(100)  # 100ms
        
        # Graph update (slower)
        self.graph_timer = QTimer()
        self.graph_timer.timeout.connect(self._update_graphs)
        self.graph_timer.start(500)  # 500ms
        
        # 3D graph update
        self.graph_3d_timer = QTimer()
        self.graph_3d_timer.timeout.connect(self._update_3d_graph)
        self.graph_3d_timer.start(200)  # 200ms

    def _update_gui(self):
        """Update the GUI with the latest sensor data."""
        try:
            # Update sensor displays
            if self.data_manager.accel_data != "N/A":
                self.accel_label.setText(f"<b>Accelerometer:</b> {self.data_manager.accel_data}")
            
            if self.data_manager.gyro_data != "N/A":
                self.gyro_label.setText(f"<b>Gyroscope:</b> {self.data_manager.gyro_data}")
            
            if self.data_manager.spo2_data != "N/A":
                self.spo2_label.setText(f"<b>SpO2:</b> {self.data_manager.spo2_data}%")
            
            if self.data_manager.heart_rate_data != "N/A":
                self.heart_rate_label.setText(f"<b>Heart Rate:</b> {self.data_manager.heart_rate_data} BPM")
            
            if self.data_manager.temp_data != "N/A":
                self.temp_label.setText(f"<b>Temperature:</b> {self.data_manager.temp_data} °C")
            
            if self.data_manager.hearttemp_data != "N/A":
                self.hearttemp_label.setText(f"<b>Heart Temp:</b> {self.data_manager.hearttemp_data} °C")
            
            if self.data_manager.pedometer_data != "N/A":
                self.pedometer_label.setText(f"<b>Steps Taken:</b> {self.data_manager.pedometer_data}")

        except Exception as e:
            logger.error(f"Error updating GUI: {str(e)}")

    def _update_graphs(self):
        """Update all graphs with new data."""
        try:
            if self.data_manager.temp_data != "N/A" and self.data_manager.hearttemp_data != "N/A":
                timestamp = datetime.now()
                
                # Limit data points
                max_points = self.data_manager.graph_data_points
                
                # Update temperature graph
                if not hasattr(self, 'temp_timestamps'):
                    self.temp_timestamps = []
                    self.temp_values = []
                    self.hearttemp_values = []
                
                self.temp_timestamps.append(timestamp)
                self.temp_values.append(float(self.data_manager.temp_data))
                self.hearttemp_values.append(float(self.data_manager.hearttemp_data))
                
                if len(self.temp_timestamps) > max_points:
                    self.temp_timestamps = self.temp_timestamps[-max_points:]
                    self.temp_values = self.temp_values[-max_points:]
                    self.hearttemp_values = self.hearttemp_values[-max_points:]
                
                self.line_temp.set_data(self.temp_timestamps, self.temp_values)
                self.line_hearttemp.set_data(self.temp_timestamps, self.hearttemp_values)
                self.ax_temp.relim()
                self.ax_temp.autoscale_view()
                self._adjust_time_axis(self.ax_temp, self.temp_timestamps)
                self.canvas_temp.draw()
            
            # Update HR/SpO2 graph
            if self.data_manager.heart_rate_data != "N/A" and self.data_manager.spo2_data != "N/A":
                if not hasattr(self, 'hr_timestamps'):
                    self.hr_timestamps = []
                    self.hr_values = []
                    self.spo2_values = []
                
                self.hr_timestamps.append(timestamp)
                self.hr_values.append(float(self.data_manager.heart_rate_data))
                self.spo2_values.append(float(self.data_manager.spo2_data))
                
                if len(self.hr_timestamps) > max_points:
                    self.hr_timestamps = self.hr_timestamps[-max_points:]
                    self.hr_values = self.hr_values[-max_points:]
                    self.spo2_values = self.spo2_values[-max_points:]
                
                self.line_hr.set_data(self.hr_timestamps, self.hr_values)
                self.line_spo2.set_data(self.hr_timestamps, self.spo2_values)
                self.ax_hr.relim()
                self.ax_hr.autoscale_view()
                self._adjust_time_axis(self.ax_hr, self.hr_timestamps)
                self.canvas_hr.draw()
            
            # Update motion graph
            if self.data_manager.accel_data != "N/A":
                if not hasattr(self, 'accel_timestamps'):
                    self.accel_timestamps = []
                    self.accel_x_values = []
                    self.accel_y_values = []
                    self.accel_z_values = []
                
                x, y, z = self._parse_accel_data(self.data_manager.accel_data)
                
                self.accel_timestamps.append(timestamp)
                self.accel_x_values.append(x)
                self.accel_y_values.append(y)
                self.accel_z_values.append(z)
                
                if len(self.accel_timestamps) > max_points:
                    self.accel_timestamps = self.accel_timestamps[-max_points:]
                    self.accel_x_values = self.accel_x_values[-max_points:]
                    self.accel_y_values = self.accel_y_values[-max_points:]
                    self.accel_z_values = self.accel_z_values[-max_points:]
                
                self.line_accel_x.set_data(self.accel_timestamps, self.accel_x_values)
                self.line_accel_y.set_data(self.accel_timestamps, self.accel_y_values)
                self.line_accel_z.set_data(self.accel_timestamps, self.accel_z_values)
                self.ax_motion.relim()
                self.ax_motion.autoscale_view()
                self._adjust_time_axis(self.ax_motion, self.accel_timestamps)
                self.canvas_motion.draw()
                
        except Exception as e:
            logger.error(f"Error updating graphs: {str(e)}")

    def _parse_accel_data(self, accel_str: str) -> Tuple[float, float, float]:
        """Parse accelerometer data string into x, y, z values."""
        try:
            parts = accel_str.split("X: ")[1].split(",")
            x = float(parts[0])
            y = float(parts[1].split("Y: ")[1])
            z = float(parts[2].split("Z: ")[1])
            return x, y, z
        except Exception as e:
            logger.error(f"Error parsing accelerometer data: {str(e)}")
            return 0.0, 0.0, 0.0

    def _adjust_time_axis(self, ax, timestamps):
        """Adjust time axis based on data duration."""
        if len(timestamps) > 1:
            duration = (timestamps[-1] - timestamps[0]).total_seconds()
            ax.set_xlim(timestamps[0], timestamps[-1])
            
            if duration <= 60:  # < 1 minute
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
                ax.xaxis.set_major_locator(mdates.SecondLocator(interval=5))
            elif duration <= 3600:  # < 1 hour
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
                ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=1))
            else:  # >= 1 hour
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
                ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))

    def _update_3d_graph(self):
        """Update the 3D orientation graph."""
        try:
            if self.data_manager.gyro_data != "N/A":
                # Parse gyro data
                x, y, z = self._parse_gyro_data(self.data_manager.gyro_data)
                
                # Update arrows
                self.arrow_x.remove()
                self.arrow_y.remove()
                self.arrow_z.remove()
                
                self.arrow_x = self.ax_3d.quiver(0, 0, 0, x, 0, 0, color='r', label='X')
                self.arrow_y = self.ax_3d.quiver(0, 0, 0, 0, y, 0, color='g', label='Y')
                self.arrow_z = self.ax_3d.quiver(0, 0, 0, 0, 0, z, color='b', label='Z')
                
                self.canvas_3d.draw()
        except Exception as e:
            logger.error(f"Error updating 3D graph: {str(e)}")

    def _parse_gyro_data(self, gyro_str: str) -> Tuple[float, float, float]:
        """Parse gyroscope data string into x, y, z values."""
        try:
            parts = gyro_str.split("X: ")[1].split(",")
            x = float(parts[0])
            y = float(parts[1].split("Y: ")[1])
            z = float(parts[2].split("Z: ")[1])
            return x, y, z
        except Exception as e:
            logger.error(f"Error parsing gyroscope data: {str(e)}")
            return 0.0, 0.0, 0.0

    def _calibrate_accelerometer(self):
        """Calibrate the accelerometer."""
        try:
            QMessageBox.information(self, "Calibration", 
                                   "Place the device on a flat surface and keep it still during calibration.")
            
            # Collect samples
            samples = []
            for _ in range(100):
                if self.data_manager.accel_data != "N/A":
                    x, y, z = self._parse_accel_data(self.data_manager.accel_data)
                    samples.append((x, y, z))
                QApplication.processEvents()
                QThread.msleep(10)
            
            if not samples:
                raise ValueError("No accelerometer data received during calibration")
            
            # Calculate biases
            avg_x = sum(s[0] for s in samples) / len(samples)
            avg_y = sum(s[1] for s in samples) / len(samples)
            avg_z = (sum(s[2] for s in samples) / len(samples)) - 1.0  # Subtract 1g for Z
            
            with self.data_manager.lock:
                self.data_manager.accel_bias = {"x": avg_x, "y": avg_y, "z": avg_z}
            
            QMessageBox.information(self, "Success", 
                                  f"Accelerometer calibrated:\nX: {avg_x:.4f}\nY: {avg_y:.4f}\nZ: {avg_z:.4f}")
        except Exception as e:
            logger.error(f"Accelerometer calibration failed: {str(e)}")
            QMessageBox.critical(self, "Error", f"Calibration failed:\n{str(e)}")

    def _calibrate_gyroscope(self):
        """Calibrate the gyroscope."""
        try:
            QMessageBox.information(self, "Calibration", 
                                   "Keep the device completely still during gyroscope calibration.")
            
            # Collect samples
            samples = []
            for _ in range(100):
                if self.data_manager.gyro_data != "N/A":
                    x, y, z = self._parse_gyro_data(self.data_manager.gyro_data)
                    samples.append((x, y, z))
                QApplication.processEvents()
                QThread.msleep(10)
            
            if not samples:
                raise ValueError("No gyroscope data received during calibration")
            
            # Calculate biases
            avg_x = sum(s[0] for s in samples) / len(samples)
            avg_y = sum(s[1] for s in samples) / len(samples)
            avg_z = sum(s[2] for s in samples) / len(samples)
            
            with self.data_manager.lock:
                self.data_manager.gyro_bias = {"x": avg_x, "y": avg_y, "z": avg_z}
            
            QMessageBox.information(self, "Success", 
                                  f"Gyroscope calibrated:\nX: {avg_x:.4f}\nY: {avg_y:.4f}\nZ: {avg_z:.4f}")
        except Exception as e:
            logger.error(f"Gyroscope calibration failed: {str(e)}")
            QMessageBox.critical(self, "Error", f"Calibration failed:\n{str(e)}")

    def _save_calibration(self):
        """Save calibration data to file."""
        try:
            self.data_manager.save_calibration()
            QMessageBox.information(self, "Success", "Calibration data saved successfully.")
        except Exception as e:
            logger.error(f"Error saving calibration: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to save calibration:\n{str(e)}")

    def _open_settings_window(self):
        """Open the settings window."""
        self.settings_window = SettingsWindow(self, self.data_manager)
        self.settings_window.exec_()

    def _open_customise_window(self):
        """Open the customization window."""
        self.customise_window = CustomiseWindow(self, self.data_manager)
        if self.customise_window.exec_():
            # Update graph colors if changed
            self.line_temp.set_color(self.data_manager.graph_colors["temp"])
            self.line_hearttemp.set_color(self.data_manager.graph_colors["hearttemp"])
            self.line_hr.set_color(self.data_manager.graph_colors["hr"])
            self.line_spo2.set_color(self.data_manager.graph_colors["spo2"])
            
            # Redraw graphs
            self.canvas_temp.draw()
            self.canvas_hr.draw()

    def _open_pop_out_window(self):
        """Open the pop-out window."""
        if not hasattr(self, 'pop_out_window') or not self.pop_out_window.isVisible():
            self.pop_out_window = PopOutWindow(self.data_manager, self)
        self.pop_out_window.show()

    def _return_to_intro(self):
        """Return to the introductory window."""
        self.close()
        self.intro_window = IntroWindow(self.data_manager)
        self.intro_window.show()

    def closeEvent(self, event):
        """Clean up resources when closing."""
        self.gui_timer.stop()
        self.graph_timer.stop()
        self.graph_3d_timer.stop()
        event.accept()

class PopOutWindow(QDialog):
    def __init__(self, data_manager, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self._setup_ui()
        self._start_update_timers()

    def _setup_ui(self):
        """Initialize the pop-out window UI."""
        self.setWindowTitle("Sensor Data Summary")
        self.setGeometry(100, 100, 400, 600)
        self.setStyleSheet("""
            QDialog {
                background: #082124;
                color: #CBE896;
            }
            QLabel {
                font-size: 12px;
            }
        """)

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        # Sensor data labels
        self.sensor_labels = {
            "accel": QLabel("<b>Accelerometer:</b> N/A"),
            "gyro": QLabel("<b>Gyroscope:</b> N/A"),
            "spo2": QLabel("<b>SpO2:</b> N/A%"),
            "heart_rate": QLabel("<b>Heart Rate:</b> N/A BPM"),
            "temp": QLabel("<b>Temperature:</b> N/A °C"),
            "hearttemp": QLabel("<b>Heart Temp:</b> N/A °C"),
            "pedometer": QLabel("<b>Steps:</b> N/A")
        }

        for label in self.sensor_labels.values():
            label.setStyleSheet("border: 1px solid #1E4E54; padding: 5px;")
            layout.addWidget(label)

        # Temperature graph
        self.fig_temp, self.ax_temp = plt.subplots(figsize=(4, 2))
        self._configure_temp_graph()
        self.canvas_temp = FigureCanvas(self.fig_temp)
        layout.addWidget(self.canvas_temp)

        # HR/SpO2 graph
        self.fig_hr, self.ax_hr = plt.subplots(figsize=(4, 2))
        self._configure_hr_graph()
        self.canvas_hr = FigureCanvas(self.fig_hr)
        layout.addWidget(self.canvas_hr)

        self.setLayout(layout)

    def _configure_temp_graph(self):
        """Configure the temperature graph for pop-out."""
        self.ax_temp.clear()
        self.ax_temp.set_title("Temperature", fontsize=10)
        self.line_temp, = self.ax_temp.plot([], [], lw=1, label="Body", 
                                          color=self.data_manager.graph_colors["temp"])
        self.line_hearttemp, = self.ax_temp.plot([], [], lw=1, label="Heart", 
                                               color=self.data_manager.graph_colors["hearttemp"])
        self.ax_temp.legend(fontsize=8)
        self.ax_temp.grid(True)
        self._configure_time_axis(self.ax_temp)

    def _configure_hr_graph(self):
        """Configure the HR/SpO2 graph for pop-out."""
        self.ax_hr.clear()
        self.ax_hr.set_title("Heart Rate & SpO2", fontsize=10)
        self.line_hr, = self.ax_hr.plot([], [], lw=1, label="HR", 
                                      color=self.data_manager.graph_colors["hr"])
        self.line_spo2, = self.ax_hr.plot([], [], lw=1, label="SpO2", 
                                        color=self.data_manager.graph_colors["spo2"])
        self.ax_hr.legend(fontsize=8)
        self.ax_hr.grid(True)
        self._configure_time_axis(self.ax_hr)

    def _configure_time_axis(self, ax):
        """Configure time axis for pop-out graphs."""
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        ax.xaxis.set_major_locator(mdates.SecondLocator(interval=5))

    def _start_update_timers(self):
        """Start timers for updating the pop-out window."""
        self.gui_timer = QTimer()
        self.gui_timer.timeout.connect(self._update_gui)
        self.gui_timer.start(200)  # 200ms

        self.graph_timer = QTimer()
        self.graph_timer.timeout.connect(self._update_graphs)
        self.graph_timer.start(1000)  # 1s

    def _update_gui(self):
        """Update the sensor data displays."""
        try:
            self.sensor_labels["accel"].setText(f"<b>Accelerometer:</b> {self.data_manager.accel_data}")
            self.sensor_labels["gyro"].setText(f"<b>Gyroscope:</b> {self.data_manager.gyro_data}")
            self.sensor_labels["spo2"].setText(f"<b>SpO2:</b> {self.data_manager.spo2_data}%")
            self.sensor_labels["heart_rate"].setText(f"<b>Heart Rate:</b> {self.data_manager.heart_rate_data} BPM")
            self.sensor_labels["temp"].setText(f"<b>Temperature:</b> {self.data_manager.temp_data} °C")
            self.sensor_labels["hearttemp"].setText(f"<b>Heart Temp:</b> {self.data_manager.hearttemp_data} °C")
            self.sensor_labels["pedometer"].setText(f"<b>Steps:</b> {self.data_manager.pedometer_data}")
        except Exception as e:
            logger.error(f"Error updating pop-out GUI: {str(e)}")

    def _update_graphs(self):
        """Update the pop-out graphs."""
        try:
            if (self.data_manager.temp_data != "N/A" and 
                self.data_manager.hearttemp_data != "N/A"):
                
                if not hasattr(self, 'temp_timestamps'):
                    self.temp_timestamps = []
                    self.temp_values = []
                    self.hearttemp_values = []
                
                timestamp = datetime.now()
                self.temp_timestamps.append(timestamp)
                self.temp_values.append(float(self.data_manager.temp_data))
                self.hearttemp_values.append(float(self.data_manager.hearttemp_data))
                
                # Limit data points
                max_points = min(50, self.data_manager.graph_data_points)
                if len(self.temp_timestamps) > max_points:
                    self.temp_timestamps = self.temp_timestamps[-max_points:]
                    self.temp_values = self.temp_values[-max_points:]
                    self.hearttemp_values = self.hearttemp_values[-max_points:]
                
                # Update temperature graph
                self.line_temp.set_data(self.temp_timestamps, self.temp_values)
                self.line_hearttemp.set_data(self.temp_timestamps, self.hearttemp_values)
                self.ax_temp.relim()
                self.ax_temp.autoscale_view()
                self._adjust_time_axis(self.ax_temp, self.temp_timestamps)
                self.canvas_temp.draw()
            
            if (self.data_manager.heart_rate_data != "N/A" and 
                self.data_manager.spo2_data != "N/A"):
                
                if not hasattr(self, 'hr_timestamps'):
                    self.hr_timestamps = []
                    self.hr_values = []
                    self.spo2_values = []
                
                self.hr_timestamps.append(timestamp)
                self.hr_values.append(float(self.data_manager.heart_rate_data))
                self.spo2_values.append(float(self.data_manager.spo2_data))
                
                if len(self.hr_timestamps) > max_points:
                    self.hr_timestamps = self.hr_timestamps[-max_points:]
                    self.hr_values = self.hr_values[-max_points:]
                    self.spo2_values = self.spo2_values[-max_points:]
                
                # Update HR/SpO2 graph
                self.line_hr.set_data(self.hr_timestamps, self.hr_values)
                self.line_spo2.set_data(self.hr_timestamps, self.spo2_values)
                self.ax_hr.relim()
                self.ax_hr.autoscale_view()
                self._adjust_time_axis(self.ax_hr, self.hr_timestamps)
                self.canvas_hr.draw()
                
        except Exception as e:
            logger.error(f"Error updating pop-out graphs: {str(e)}")

    def _adjust_time_axis(self, ax, timestamps):
        """Adjust time axis based on data duration."""
        if len(timestamps) > 1:
            duration = (timestamps[-1] - timestamps[0]).total_seconds()
            ax.set_xlim(timestamps[0], timestamps[-1])
            
            if duration <= 60:  # < 1 minute
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
                ax.xaxis.set_major_locator(mdates.SecondLocator(interval=5))
            elif duration <= 3600:  # < 1 hour
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
                ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=1))
            else:  # >= 1 hour
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
                ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))

    def closeEvent(self, event):
        """Clean up resources when closing."""
        self.gui_timer.stop()
        self.graph_timer.stop()
        event.accept()

if __name__ == "__main__":
    # Set up application
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon('app_icon.png'))
    app.setStyle('Fusion')
    
    # Initialize data manager and main window
    data_manager = SensorDataManager()
    intro_window = IntroWindow(data_manager)
    intro_window.show()
    
    # Start application
    sys.exit(app.exec_())