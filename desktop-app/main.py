import asyncio
import math
from bleak import BleakScanner, BleakClient
import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QPushButton, QVBoxLayout, QWidget, QListWidget,
    QMessageBox, QCheckBox, QColorDialog, QFileDialog, QDialog, QSpinBox, QLineEdit,
    QHBoxLayout, QGridLayout, QDialogButtonBox, QGroupBox, QScrollArea, QTextEdit, QGraphicsView, QGraphicsScene, QProgressDialog
)
from PyQt5.QtCore import Qt, QTimer, QEvent, QDateTime
from PyQt5.QtGui import QPixmap, QFont, QImage, QIcon
import csv
from datetime import datetime, timedelta
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
from threading import Lock

# Defined UUIDs (matching those in the ESP32 code)
SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
ACCEL_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
GYRO_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a9"
SPO2_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26aa"
HEART_RATE_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26ab"
TEMP_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26ac"
HEARTTEMP_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26af"  # UUID for heart temperature (internal temperature)
PEDOMETER_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26b0"  # New UUID for pedometer


# ESP32 MAC Address (for testing purposes only)
# ESP32_ADDRESS = "10:06:1c:17:65:7e"

class SensorDataManager:
    def __init__(self):
        self.lock = Lock()  # Thread-safe lock for sensor data updates
        self.accel_data = "N/A"
        self.gyro_data = "N/A"
        self.spo2_data = "N/A"
        self.heart_rate_data = "N/A"
        self.temp_data = "N/A"
        self.hearttemp_data = "N/A"
        self.pedometer_data = "N/A" 

        self.visible_sensors = {
            "accel": True,
            "gyro": True,
            "spo2": True,
            "heart_rate": True,
            "temp": True,
            "hearttemp": True,
            "pedometer": True  # New pedometer visibility
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
        self.LOG_FILE = "ui/output/sensor_data.csv"
        self.PROGRAM_VERSION = "1.0.0"
        self.ble_connected = False
        self.last_log_time = None
        self.graph_data_points = 10  # Default number of data points to display
        self.linear_accel = 0.0  # Store linear acceleration

        # Load calibration biases from file (if exists)
        self.load_calibration()

    def calculate_linear_acceleration(self, x, y, z):
        """Calculate the magnitude of linear acceleration (in m/s²)"""
        # Remove gravity component (assuming z-axis is up)
        x = float(x) - self.accel_bias["x"]
        y = float(y) - self.accel_bias["y"]
        z = float(z) - self.accel_bias["z"] - 1.0  # Subtract 1g (9.81 m/s²)
        
        # Convert to m/s² (assuming raw values are in g)
        x *= 9.81
        y *= 9.81
        z *= 9.81
        
        # Calculate magnitude
        self.linear_accel = math.sqrt(x**2 + y**2 + z**2)
        return self.linear_accel
    
    def load_calibration(self):
        """Load calibration biases from a file."""
        try:
            with open("resources/calibration.json", "r") as f:
                calibration = json.load(f)
                self.accel_bias = calibration["accel_bias"]
                self.gyro_bias = calibration["gyro_bias"]
        except FileNotFoundError:
            print("No calibration file found. Starting with default biases.")
            self.accel_bias = {"x": 0.0, "y": 0.0, "z": 0.0}
            self.gyro_bias = {"x": 0.0, "y": 0.0, "z": 0.0}

    def save_calibration(self):
        """Save calibration biases to a file."""
        with open("resources/calibration.json", "w") as f:
            json.dump({"accel_bias": self.accel_bias, "gyro_bias": self.gyro_bias}, f)

    def log_data(self, timestamp, accel, gyro, spo2, heart_rate, temp, hearttemp):
        """Log sensor data to a CSV file once per second."""
        if self.last_log_time is None or (datetime.now() - self.last_log_time).total_seconds() >= 1:
            with open(self.LOG_FILE, mode="a", newline="") as file:
                writer = csv.writer(file)
                writer.writerow([timestamp, accel, gyro, spo2, heart_rate, temp, hearttemp])
            self.last_log_time = datetime.now()

    def play_sound(self, filename):
        """Play a sound if available, otherwise do nothing silently."""
        try:
            if os.path.exists(filename) and os.name == "nt":  # Windows
                winsound.PlaySound(filename, winsound.SND_ASYNC)
            elif os.path.exists(filename):  # macOS/Linux
                os.system(f"afplay {filename} &")
        except Exception as e:
            print(f"Sound playback error: {e}")

    def update_sensor_data(self, sensor_type, data):
        value = data.decode("utf-8")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.lock:  # Thread-safe update
            if sensor_type == "accel":
                x, y, z = value.split(',')
                self.accel_data = f"X: {x}, Y: {y}, Z: {z}"
                self.calculate_linear_acceleration(x, y, z)  # Calculate linear acceleration
                self.log_data(timestamp, value, self.gyro_data, self.spo2_data, self.heart_rate_data, self.temp_data, self.hearttemp_data)
            elif sensor_type == "gyro":
                x, y, z = value.split(',')
                self.gyro_data = f"X: {x}, Y: {y}, Z: {z}"
                self.log_data(timestamp, self.accel_data, value, self.spo2_data, self.heart_rate_data, self.temp_data, self.hearttemp_data)
            elif sensor_type == "spo2":
                self.spo2_data = value
                self.log_data(timestamp, self.accel_data, self.gyro_data, value, self.heart_rate_data, self.temp_data, self.hearttemp_data)
            elif sensor_type == "heart_rate":
                self.heart_rate_data = value
                self.log_data(timestamp, self.accel_data, self.gyro_data, self.spo2_data, value, self.temp_data, self.hearttemp_data)
            elif sensor_type == "temp":
                self.temp_data = value
                self.log_data(timestamp, self.accel_data, self.gyro_data, self.spo2_data, self.heart_rate_data, value, self.hearttemp_data)
            elif sensor_type == "hearttemp":  # Handle heart temperature data
                self.hearttemp_data = value
                self.log_data(timestamp, self.accel_data, self.gyro_data, self.spo2_data, self.heart_rate_data, self.temp_data, value)
            elif sensor_type == "pedometer":  # Handle pedometer data
                self.pedometer_data = value
                self.log_data(timestamp, self.accel_data, self.gyro_data, self.spo2_data, self.heart_rate_data, self.temp_data, self.hearttemp_data)

# Settings Window
class SettingsWindow(QDialog):
    def __init__(self, parent=None, data_manager=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.setWindowTitle("Settings")
        self.setWindowFlags(self.windowFlags() | Qt.WindowContextHelpButtonHint)  # Add the question mark button
        self.setStyleSheet("background: #0B2E33; color: #93B1B5;")

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        # SpO2 threshold
        self.spo2_threshold = QSpinBox()
        self.spo2_threshold.setValue(self.data_manager.alarm_thresholds["spo2"])
        self.spo2_threshold.setRange(0, 100)
        layout.addWidget(QLabel("SpO2 Alarm Threshold (%)"))
        layout.addWidget(self.spo2_threshold)

        # CSV path label and button
        self.path_label = QLabel(f"Current CSV Path: {self.data_manager.LOG_FILE}")
        layout.addWidget(self.path_label)
        self.path_button = QPushButton("Select Data Directory")
        self.path_button.clicked.connect(self.select_directory)
        layout.addWidget(self.path_button)

        # Clear data button
        self.clear_button = QPushButton("Clear Data")
        self.clear_button.clicked.connect(self.clear_data)
        layout.addWidget(self.clear_button)

        # Save and Return button
        self.save_return_button = QPushButton("Save and Return")
        self.save_return_button.clicked.connect(self.save_and_return)
        layout.addWidget(self.save_return_button)

        self.setLayout(layout)
        self.adjustSize()
        self.setFixedSize(self.size())

    def save_and_return(self):
        """Save settings and return to the MainProgram."""
        self.data_manager.alarm_thresholds["spo2"] = self.spo2_threshold.value()
        self.accept()  # Close the window

    def select_directory(self):
        """Select a directory for saving the CSV file."""
        path = QFileDialog.getExistingDirectory(self, "Select Directory")
        if path:
            self.data_manager.LOG_FILE = os.path.join(path, "sensor_data.csv")
            self.path_label.setText(f"Current CSV Path: {self.data_manager.LOG_FILE}")
            QMessageBox.information(self, "Success", f"Data will be saved to: {self.data_manager.LOG_FILE}")

    def clear_data(self):
        with open(self.data_manager.LOG_FILE, "w") as f:
            f.write("")
        QMessageBox.information(self, "Success", "Data cleared successfully")

    def event(self, event):
        """Override the event method to handle the question mark button click."""
        if event.type() == QEvent.EnterWhatsThisMode:
            self.show_settingshelp()
            return True
        return super().event(event)

    def show_settingshelp(self):
        """Display a help message for the window."""
        QMessageBox.information(self, "Help", "This is the Settings window. Use this window to configure alarm thresholds, clear data, and change the data directory.")
        
    def accept(self):
        self.data_manager.alarm_thresholds["spo2"] = self.spo2_threshold.value()
        super().accept()

# Customise Window
class CustomiseWindow(QDialog):
    def __init__(self, parent=None, data_manager=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.setWindowTitle("Customise")
        self.setWindowFlags(self.windowFlags() | Qt.WindowContextHelpButtonHint)  # Add the question mark button
        self.setStyleSheet("background: #0B2E33; color: #93B1B5;")

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        # Checkboxes in a 3x2 grid
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(10)
        self.checkboxes = {}  # Dictionary to store checkboxes
        sensors = list(self.data_manager.visible_sensors.keys())
        for i, sensor in enumerate(sensors):
            row = i // 2
            col = i % 2
            cb = QCheckBox(sensor.replace("_", " ").title())
            cb.setChecked(self.data_manager.visible_sensors[sensor])
            self.checkboxes[sensor] = cb  # Store the checkbox in the dictionary
            self.grid_layout.addWidget(cb, row, col)
        layout.addLayout(self.grid_layout)

        # Spin box for data points
        self.data_points_spinbox = QSpinBox()
        self.data_points_spinbox.setValue(self.data_manager.graph_data_points)
        self.data_points_spinbox.setRange(10, 1000)
        layout.addWidget(QLabel("Number of Data Points to Display:"))
        layout.addWidget(self.data_points_spinbox)

        # Color buttons in a 2x2 grid
        self.color_grid_layout = QGridLayout()
        self.color_grid_layout.setSpacing(10)
        graphs = list(self.data_manager.graph_colors.keys())
        for i, graph in enumerate(graphs):
            row = i // 2
            col = i % 2
            btn = QPushButton(f"Choose {graph.title()} Color")
            btn.clicked.connect(lambda _, g=graph: self.choose_color(g))
            self.color_grid_layout.addWidget(btn, row, col)
        layout.addLayout(self.color_grid_layout)

        # Save and Return button
        self.save_return_button = QPushButton("Save and Return")
        self.save_return_button.clicked.connect(self.save_and_return)
        layout.addWidget(self.save_return_button)

        self.setLayout(layout)
        self.adjustSize()
        self.setFixedSize(self.size())

    def save_and_return(self):
        """Save settings and return to the IntroWindow."""
        for sensor, cb in self.checkboxes.items():
            self.data_manager.visible_sensors[sensor] = cb.isChecked()
        self.data_manager.graph_data_points = self.data_points_spinbox.value()        
        self.accept()  # Close the window

    def choose_color(self, graph):
        color = QColorDialog.getColor()
        if color.isValid():
            self.data_manager.graph_colors[graph] = color.name()
            self.sender().setStyleSheet(f"background-color: {color.name()}")
            
    def event(self, event):
        """Override the event method to handle the question mark button click."""
        if event.type() == QEvent.EnterWhatsThisMode:
            self.show_customhelp()
            return True
        return super().event(event)

    def show_customhelp(self):
        """Display a help message for the window."""
        QMessageBox.information(self, "Help", "This is the Customise window. Use this window to toggle sensor visibility, change graph colors, and adjust the number of data points displayed.")

# Introductory Window
class IntroWindow(QMainWindow):
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self.setWindowTitle("Health Monitoring System")
        self.setGeometry(100, 100, 500, 400)
        self.setStyleSheet("background: #082124; color: #CBE896;")

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.layout = QVBoxLayout(self.central_widget)

        # Program version label
        self.version_label = QLabel(f"Version: {self.data_manager.PROGRAM_VERSION}")
        self.version_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self.layout.addWidget(self.version_label)

        # Main label (centered)
        self.main_label = QLabel("Health Monitoring System")
        self.main_label.setFont(QFont("Roboto", 24))
        self.main_label.setStyleSheet("font-size: 28px; font-weight: bold;")
        self.main_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.main_label)

        # Buttons
        self.connect_button = QPushButton("Connect")
        self.connect_button.setIcon(QIcon("ui/icons/connect_icon.png"))
        self.connect_button.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; border-radius: 10px; padding: 5px; }"
                                         "QPushButton:hover { background-color: #45a049; }")
        self.connect_button.clicked.connect(self.open_connect_window)
        self.layout.addWidget(self.connect_button)

        self.settings_button = QPushButton("Settings")
        self.settings_button.setIcon(QIcon("ui/icons/settings_icon.png"))
        self.settings_button.setStyleSheet("QPushButton { background-color: #008CBA; color: white; border-radius: 10px; padding: 5px; }"
                                          "QPushButton:hover { background-color: #007B9E; }")
        self.settings_button.clicked.connect(self.open_settings_window)
        self.layout.addWidget(self.settings_button)

        self.customise_button = QPushButton("Customise")
        self.customise_button.setIcon(QIcon("ui/icons/customise_icon.png"))
        self.customise_button.setStyleSheet("QPushButton { background-color: #FFA500; color: white; border-radius: 10px; padding: 5px; }"
                                            "QPushButton:hover { background-color: #FF8C00; }")
        self.customise_button.clicked.connect(self.open_customise_window)
        self.layout.addWidget(self.customise_button)

        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.start_program)
        self.start_button.setIcon(QIcon("ui/icons/start_icon.png"))
        self.start_button.setStyleSheet("QPushButton { background-color: #f44336; color: white; border-radius: 10px; padding: 5px; }"
                                       "QPushButton:hover { background-color: #e53935; }")
        self.layout.addWidget(self.start_button)

        # Connection status label (centered)
        self.connection_status = QLabel("Device: Not Connected")
        self.connection_status.setFont(QFont("Roboto", 10))
        self.connection_status.setAlignment(Qt.AlignCenter)
        self.connection_status.setStyleSheet("color: #FF6347;")  # Red for disconnect

        self.layout.addWidget(self.connection_status)

    def update_connection_status(self, connected):
        """Update the connection status label."""
        status = "Connected" if connected else "Not Connected"
        self.connection_status.setText(f"Device: {status}")

    def open_connect_window(self):
        """Open the Connect window to scan and pair with BLE devices."""
        self.connect_window = QDialog(self)
        self.connect_window.setWindowTitle("Connect to Device")
        self.connect_window.setGeometry(200, 200, 400, 300)

        self.connect_layout = QVBoxLayout(self.connect_window)
        self.connect_layout.setSpacing(15)

        # Instructions
        instructions = QLabel(
            "1. Click 'Scan for Devices'\n"
            "2. Select your device from the list\n"
            "3. Click 'Connect'\n\n"
            "Ensure your device is powered on and in range."
        )
        instructions.setWordWrap(True)
        self.connect_layout.addWidget(instructions)
        
        # Scan button
        self.scan_button = QPushButton("Scan for Devices")
        self.scan_button.clicked.connect(self.scan_ble_devices)
        self.connect_layout.addWidget(self.scan_button)

        # Listbox to display devices
        self.device_listbox = QListWidget()
        self.connect_layout.addWidget(self.device_listbox)

        # Connect button
        self.connect_button = QPushButton("Connect to Selected Device")
        self.connect_button.clicked.connect(self.connect_to_device)
        self.connect_layout.addWidget(self.connect_button)

        self.connect_window.exec_()

    def scan_ble_devices(self):
        """Scan for BLE devices and display them in the listbox."""
        async def scan():
            self.device_listbox.clear()  # Clear the listbox
            devices = await BleakScanner.discover()
            for device in devices:
                self.device_listbox.addItem(f"{device.name} - {device.address}")

        # Run the scan in a separate thread
        threading.Thread(target=asyncio.run, args=(scan(),), daemon=True).start()

    def connect_to_device(self):
        """Connect to the selected BLE device."""
        selected_device = self.device_listbox.currentItem()
        if not selected_device:
            QMessageBox.critical(self, "Error", "No device selected!")
            return

        # Extract the device address from the selected item
        device_address = selected_device.text().split(" - ")[-1]

        # Start the BLE connection in a separate thread
        threading.Thread(target=asyncio.run, args=(self.read_ble_data(device_address),), daemon=True).start()

    async def read_ble_data(self, address):
        while self.data_manager.running:
            try:
                async with BleakClient(address) as client:
                    print(f"Connected to {address}")
                    self.data_manager.ble_connected = True
                    self.update_connection_status(self.data_manager.ble_connected)
                    if hasattr(self, 'connect_window'):
                        self.connect_window.close()  # Close the connect window after successful connection

                    # Enable notifications for all characteristics
                    await client.start_notify(ACCEL_UUID, lambda _, data: self.data_manager.update_sensor_data("accel", data))
                    await client.start_notify(GYRO_UUID, lambda _, data: self.data_manager.update_sensor_data("gyro", data))
                    await client.start_notify(SPO2_UUID, lambda _, data: self.data_manager.update_sensor_data("spo2", data))
                    await client.start_notify(HEART_RATE_UUID, lambda _, data: self.data_manager.update_sensor_data("heart_rate", data))
                    await client.start_notify(TEMP_UUID, lambda _, data: self.data_manager.update_sensor_data("temp", data))
                    await client.start_notify(HEARTTEMP_UUID, lambda _, data: self.data_manager.update_sensor_data("hearttemp", data))  # Heart temperature notifications
                    await client.start_notify(PEDOMETER_UUID, lambda _, data: self.data_manager.update_sensor_data("pedometer", data))  # Enable pedometer notifications

                    print("Notifications enabled. Waiting for updates...")
                    while self.data_manager.running:
                        await asyncio.sleep(0.1)  # Keep the connection alive
            except Exception as e:
                print(f"BLE connection error: {e}. Retrying in 5 seconds...")
                self.data_manager.ble_connected = False
                self.update_connection_status(self.data_manager.ble_connected)
                if main_program_window and main_program_window.isVisible():
                    QMessageBox.critical(main_program_window, "Disconnected", "Bluetooth device disconnected. Please reconnect.")
                    main_program_window.return_to_intro()
                await asyncio.sleep(5)
            finally:
                # Cleanup resources
                if hasattr(self, 'client') and self.client.is_connected:
                    await self.client.disconnect()
                    print("BLE client disconnected and resources released.")

    def open_settings_window(self):
        """Open the Settings window to input age, weight, and clear data."""
        self.settings_window = SettingsWindow(self, self.data_manager)
        if self.settings_window.exec_():
            # Update alarm thresholds
            self.data_manager.alarm_thresholds["spo2"] = self.settings_window.spo2_threshold.value()

    def clear_data(self):
        """Clear saved data."""
        with open(self.data_manager.LOG_FILE, "w") as file:
            file.write("")  # Clear the file
        print("Data cleared.")

    def open_customise_window(self):
        """Open the Customise window to change data presentation."""
        self.customise_window = CustomiseWindow(self, self.data_manager)
        if self.customise_window.exec_():
            # Save settings
            for sensor, cb in self.customise_window.checkboxes.items():
                self.data_manager.visible_sensors[sensor] = cb.isChecked()
 
    def start_program(self):
        """Start the main program."""
        if not self.data_manager.ble_connected:
            QMessageBox.critical(self, "Error", "Please connect to a device first!")
            return
        self.close()  # Close the introductory window
        global main_program_window
        main_program_window = MainProgram(self.data_manager)
        main_program_window.show()

# Main Program
class MainProgram(QMainWindow):
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self.setWindowTitle("ESP32 Sensor Monitor")
        self.setWindowFlags(self.windowFlags() | Qt.WindowContextHelpButtonHint)
        self.setGeometry(100, 100, 1000, 800)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.layout = QVBoxLayout(self.central_widget)

        # Initialize calibration variables from data_manager
        self.accel_bias = self.data_manager.accel_bias
        self.gyro_bias = self.data_manager.gyro_bias
        
        # Button to access the SettingsWindow
        self.settings_button = QPushButton("Open Settings")
        self.settings_button.clicked.connect(self.open_settings_window)
        self.layout.addWidget(self.settings_button)
        
        # Button to access the CustomiseWindow
        self.customise_button = QPushButton("Customise Graphs")
        self.customise_button.clicked.connect(self.open_customise_window)
        self.layout.addWidget(self.customise_button)

        # Create horizontal layouts for the sensor data boxes
        self.sensor_data_layout = QHBoxLayout()
        self.sensor_data_layoutB = QHBoxLayout()

        # Create QLabel widgets for each sensor data
        self.accel_label = QLabel("Accelerometer: N/A")
        self.accel_label.setStyleSheet("border: 1px solid black; padding: 10px;")
        self.accel_label.setAlignment(Qt.AlignCenter)
        self.sensor_data_layout.addWidget(self.accel_label)

        self.gyro_label = QLabel("Gyroscope: N/A")
        self.gyro_label.setStyleSheet("border: 1px solid black; padding: 10px;")
        self.gyro_label.setAlignment(Qt.AlignCenter)
        self.sensor_data_layout.addWidget(self.gyro_label)
        
        self.heart_rate_label = QLabel("Heart Rate: N/A BPM")
        self.heart_rate_label.setStyleSheet("border: 1px solid black; padding: 10px;")
        self.heart_rate_label.setAlignment(Qt.AlignCenter)
        self.sensor_data_layoutB.addWidget(self.heart_rate_label)
        
        self.spo2_label = QLabel("SpO2: N/A%")
        self.spo2_label.setStyleSheet("border: 1px solid black; padding: 10px;")
        self.spo2_label.setAlignment(Qt.AlignCenter)
        self.sensor_data_layoutB.addWidget(self.spo2_label)

        self.temp_label = QLabel("Temperature: N/A °C")
        self.temp_label.setStyleSheet("border: 1px solid black; padding: 10px;")
        self.temp_label.setAlignment(Qt.AlignCenter)
        self.sensor_data_layoutB.addWidget(self.temp_label)

        self.hearttemp_label = QLabel("Heart Temperature: N/A °C")
        self.hearttemp_label.setStyleSheet("border: 1px solid black; padding: 10px;")
        self.hearttemp_label.setAlignment(Qt.AlignCenter)
        self.sensor_data_layoutB.addWidget(self.hearttemp_label)

        self.pedometer_label = QLabel("Steps Taken: N/A")
        self.pedometer_label.setStyleSheet("border: 1px solid black; padding: 10px;")
        self.pedometer_label.setAlignment(Qt.AlignCenter)
        self.sensor_data_layout.addWidget(self.pedometer_label)
        
        # Add the sensor data layouts to the main layout
        self.layout.addLayout(self.sensor_data_layout)
        self.layout.addLayout(self.sensor_data_layoutB)

        # Create a horizontal layout for the calibration buttons
        self.calib_layout = QHBoxLayout()
        
        # Add calibration buttons
        self.calibrate_accel_button = QPushButton("Calibrate Accelerometer")
        self.calibrate_accel_button.clicked.connect(self.calibrate_accelerometer)
        self.calib_layout.addWidget(self.calibrate_accel_button)

        self.calibrate_gyro_button = QPushButton("Calibrate Gyroscope")
        self.calibrate_gyro_button.clicked.connect(self.calibrate_gyroscope)
        self.calib_layout.addWidget(self.calibrate_gyro_button)
        
        self.layout.addLayout(self.calib_layout)
        
        # Alarm label
        self.alarm_label = QLabel("No Alarms")
        self.layout.addWidget(self.alarm_label)

        # Temperature Graph
        self.fig_temp = plt.figure(figsize=(8, 3))
        self.ax_temp = self.fig_temp.add_subplot(111)
        self.ax_temp.set_title("Temperature Monitoring", fontsize=12, fontweight='bold', pad=15)
        self.ax_temp.set_xlabel("Time", fontsize=10)
        self.ax_temp.set_ylabel("Temperature (°C)", fontsize=10)
        self.line_temp, = self.ax_temp.plot([], [], 
                                          lw=2, 
                                          label="Body Temperature", 
                                          color=self.data_manager.graph_colors["temp"],
                                          marker='o',
                                          markersize=4,
                                          alpha=0.7)
        self.line_hearttemp, = self.ax_temp.plot([], [], 
                                               lw=2, 
                                               label="Heart Temperature", 
                                               color=self.data_manager.graph_colors["hearttemp"],
                                               marker='s',
                                               markersize=4,
                                               alpha=0.7)
        
        # Enhance grid and ticks
        self.ax_temp.grid(True, linestyle='--', alpha=0.6)
        self.ax_temp.tick_params(axis='both', which='major', labelsize=9)
        self.ax_temp.legend(loc='upper right', fontsize=9)
        
        # Format x-axis
        self.ax_temp.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        self.ax_temp.xaxis.set_major_locator(mdates.AutoDateLocator())
        
        # Add some padding
        self.fig_temp.subplots_adjust(left=0.1, right=0.95, top=0.9, bottom=0.15)
        
        self.canvas_temp = FigureCanvas(self.fig_temp)
        self.layout.addWidget(self.canvas_temp)

        # Heart Rate & SpO2 Graph
        self.fig_hr = plt.figure(figsize=(8, 3))
        self.ax_hr = self.fig_hr.add_subplot(111)
        self.ax_hr.set_title("Heart Rate & Oxygen Saturation", fontsize=12, fontweight='bold', pad=15)
        self.ax_hr.set_xlabel("Time", fontsize=10)
        self.ax_hr.set_ylabel("Value", fontsize=10)
        
        # Create two y-axes for different scales
        self.ax_hr2 = self.ax_hr.twinx()
        self.ax_hr2.set_ylabel("SpO2 (%)", fontsize=10)
        
        self.line_hr, = self.ax_hr.plot([], [], 
                                       lw=2, 
                                       label="Heart Rate (BPM)", 
                                       color=self.data_manager.graph_colors["hr"],
                                       marker='^',
                                       markersize=4,
                                       alpha=0.7)
        self.line_spo2, = self.ax_hr2.plot([], [], 
                                         lw=2, 
                                         label="SpO2 (%)", 
                                         color=self.data_manager.graph_colors["spo2"],
                                         marker='d',
                                         markersize=4,
                                         alpha=0.7)
        
        # Enhance grid and ticks
        self.ax_hr.grid(True, linestyle='--', alpha=0.6)
        self.ax_hr.tick_params(axis='both', which='major', labelsize=9)
        self.ax_hr2.tick_params(axis='y', which='major', labelsize=9)
        
        # Combine legends
        lines = [self.line_hr, self.line_spo2]
        labels = [line.get_label() for line in lines]
        self.ax_hr.legend(lines, labels, loc='upper right', fontsize=9)
        
        # Format x-axis
        self.ax_hr.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        self.ax_hr.xaxis.set_major_locator(mdates.AutoDateLocator())
        
        # Add some padding
        self.fig_hr.subplots_adjust(left=0.1, right=0.9, top=0.9, bottom=0.15)
        
        self.canvas_hr = FigureCanvas(self.fig_hr)
        self.layout.addWidget(self.canvas_hr)

        # Create a horizontal layout for the bottom graphs
        self.bottom_graphs_layout = QHBoxLayout()

        # 3D Gyroscope Graph
        self.fig_3d = plt.figure(figsize=(6, 4))
        self.ax_3d = self.fig_3d.add_subplot(111, projection='3d')
        self.ax_3d.set_title("Gyroscope Orientation", fontsize=12, fontweight='bold', pad=15)
        self.ax_3d.set_xlabel("X", fontsize=9)
        self.ax_3d.set_ylabel("Y", fontsize=9)
        self.ax_3d.set_zlabel("Z", fontsize=9)
        
        # Initialize arrows
        self.arrow_x = self.ax_3d.quiver(0, 0, 0, 1, 0, 0, color='r', linewidth=2, arrow_length_ratio=0.2, label='X')
        self.arrow_y = self.ax_3d.quiver(0, 0, 0, 0, 1, 0, color='g', linewidth=2, arrow_length_ratio=0.2, label='Y')
        self.arrow_z = self.ax_3d.quiver(0, 0, 0, 0, 0, 1, color='b', linewidth=2, arrow_length_ratio=0.2, label='Z')
        
        # Set equal aspect ratio
        self.ax_3d.set_box_aspect([1, 1, 1])
        
        # Add legend and grid
        self.ax_3d.legend(fontsize=9)
        self.ax_3d.grid(True, linestyle='--', alpha=0.6)
        
        # Adjust viewing angle for better perspective
        self.ax_3d.view_init(elev=20, azim=45)
        
        self.canvas_3d = FigureCanvas(self.fig_3d)
        self.bottom_graphs_layout.addWidget(self.canvas_3d)

        # Linear Acceleration Graph
        self.fig_accel = plt.figure(figsize=(6, 4))
        self.ax_accel = self.fig_accel.add_subplot(111)
        self.ax_accel.set_title("Linear Acceleration", fontsize=12, fontweight='bold', pad=15)
        self.ax_accel.set_xlabel("Time", fontsize=10)
        self.ax_accel.set_ylabel("Acceleration (m/s²)", fontsize=10)
        self.line_accel, = self.ax_accel.plot([], [], 
                                            lw=2, 
                                            color='orange',
                                            marker='o',
                                            markersize=4,
                                            alpha=0.7)
        
        # Enhance grid and ticks
        self.ax_accel.grid(True, linestyle='--', alpha=0.6)
        self.ax_accel.tick_params(axis='both', which='major', labelsize=9)
        
        # Format x-axis
        self.ax_accel.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        self.ax_accel.xaxis.set_major_locator(mdates.AutoDateLocator())
        
        # Add some padding
        self.fig_accel.subplots_adjust(left=0.15, right=0.95, top=0.9, bottom=0.15)
        
        self.canvas_accel = FigureCanvas(self.fig_accel)
        self.bottom_graphs_layout.addWidget(self.canvas_accel)

        # Add the bottom graphs layout to the main layout
        self.layout.addLayout(self.bottom_graphs_layout)

        # Data for the graphs
        self.timestamps = []
        self.temp_values = []
        self.hearttemp_values = []
        self.hr_values = []
        self.spo2_values = []
        self.accel_values = []

                
        # Add a button to open the pop-out window
        self.pop_out_button = QPushButton("Open Pop-Out Window")
        self.pop_out_button.clicked.connect(self.open_pop_out_window)
        self.layout.addWidget(self.pop_out_button)
        
        # Return to Intro button
        self.return_button = QPushButton("Return to Intro")
        self.return_button.clicked.connect(self.return_to_intro)
        self.layout.addWidget(self.return_button)
        
        # Start updating the GUI and graphs
        self.update_gui()
        self.update_graphs()

        
    def open_customise_window(self):
        """Open the CustomiseWindow from the MainProgram."""
        self.customise_window = CustomiseWindow(self, self.data_manager)  # Pass `self` as parent
        if self.customise_window.exec_():
            # Update graph colors and visibility
            self.line_temp.set_color(self.data_manager.graph_colors["temp"])
            self.line_hearttemp.set_color(self.data_manager.graph_colors["hearttemp"])
            self.line_hr.set_color(self.data_manager.graph_colors["hr"])
            self.line_spo2.set_color(self.data_manager.graph_colors["spo2"])

            self.line_temp.set_visible(self.data_manager.visible_sensors["temp"])
            self.line_hearttemp.set_visible(self.data_manager.visible_sensors["hearttemp"])
            self.line_hr.set_visible(self.data_manager.visible_sensors["heart_rate"])
            self.line_spo2.set_visible(self.data_manager.visible_sensors["spo2"])
            
            # Redraw the graphs
            self.canvas_temp.draw()
            self.canvas_hr.draw()
            
    def open_settings_window(self):
        """Open the SettingsWindow from the MainProgram."""
        self.settings_window = SettingsWindow(self, self.data_manager)  # Pass `self` as parent
        if self.settings_window.exec_():
            # Save settings if the user clicks "Save and Return"
            self.data_manager.alarm_thresholds["spo2"] = self.settings_window.spo2_threshold.value()
            
    def calibrate_accelerometer(self):
        """Calibrate the accelerometer by collecting data while stationary."""
        QMessageBox.information(self, "Calibration", "Please keep the device stationary for accelerometer calibration.")
        num_samples = 100
        accel_x_sum = 0.0
        accel_y_sum = 0.0
        accel_z_sum = 0.0

        for _ in range(num_samples):
            if self.data_manager.accel_data != "N/A":
                try:
                    x, y, z = self.data_manager.accel_data.split("X: ")[1].split(",")
                    accel_x_sum += float(x)
                    accel_y_sum += float(y.split("Y: ")[1])
                    accel_z_sum += float(z.split("Z: ")[1])
                except Exception as e:
                    print(f"Error parsing accelerometer data: {e}")
            QTimer.singleShot(10, lambda: None)  # Wait for 10ms between samples
            QApplication.processEvents()  # Allow the GUI to update

        self.accel_bias["x"] = accel_x_sum / num_samples
        self.accel_bias["y"] = accel_y_sum / num_samples
        self.accel_bias["z"] = accel_z_sum / num_samples - 1.0  # Assuming Z axis is facing up (1g)

        # Update data_manager biases
        self.data_manager.accel_bias = self.accel_bias
        self.data_manager.save_calibration()
    
        QMessageBox.information(self, "Calibration Complete", f"Accelerometer calibration complete.\nBias: X={self.accel_bias['x']}, Y={self.accel_bias['y']}, Z={self.accel_bias['z']}")

    def calibrate_gyroscope(self):
        """Calibrate the gyroscope by collecting data while stationary."""
        QMessageBox.information(self, "Calibration", "Please keep the device stationary for gyroscope calibration.")
        num_samples = 100
        gyro_x_sum = 0.0
        gyro_y_sum = 0.0
        gyro_z_sum = 0.0

        for _ in range(num_samples):
            if self.data_manager.gyro_data != "N/A":
                try:
                    x, y, z = self.data_manager.gyro_data.split("X: ")[1].split(",")
                    gyro_x_sum += float(x)
                    gyro_y_sum += float(y.split("Y: ")[1])
                    gyro_z_sum += float(z.split("Z: ")[1])
                except Exception as e:
                    print(f"Error parsing gyroscope data: {e}")
            QTimer.singleShot(10, lambda: None)  # Wait for 10ms between samples
            QApplication.processEvents()  # Allow the GUI to update

        self.gyro_bias["x"] = gyro_x_sum / num_samples
        self.gyro_bias["y"] = gyro_y_sum / num_samples
        self.gyro_bias["z"] = gyro_z_sum / num_samples

        # Update data_manager biases
        self.data_manager.gyro_bias = self.gyro_bias
        self.data_manager.save_calibration()
    
        QMessageBox.information(self, "Calibration Complete", f"Gyroscope calibration complete.\nBias: X={self.gyro_bias['x']}, Y={self.gyro_bias['y']}, Z={self.gyro_bias['z']}")

    def update_gui(self):
        """Update the GUI with calibrated sensor data."""
        if self.data_manager.accel_data != "N/A":
            try:
                x, y, z = self.data_manager.accel_data.split("X: ")[1].split(",")
                x_calibrated = float(x) - self.accel_bias["x"]
                y_calibrated = float(y.split("Y: ")[1]) - self.accel_bias["y"]
                z_calibrated = float(z.split("Z: ")[1]) - self.accel_bias["z"]
                self.accel_label.setText(f"Accelerometer: X: {x_calibrated:.4f}, Y: {y_calibrated:.4f}, Z: {z_calibrated:.4f}")
            except Exception as e:
                print(f"Error updating accelerometer data: {e}")

        if self.data_manager.gyro_data != "N/A":
            try:
                x, y, z = self.data_manager.gyro_data.split("X: ")[1].split(",")
                x_calibrated = float(x) - self.gyro_bias["x"]
                y_calibrated = float(y.split("Y: ")[1]) - self.gyro_bias["y"]
                z_calibrated = float(z.split("Z: ")[1]) - self.gyro_bias["z"]
                self.gyro_label.setText(f"Gyroscope: X: {x_calibrated:.4f}, Y: {y_calibrated:.4f}, Z: {z_calibrated:.4f}")
            except Exception as e:
                print(f"Error updating gyroscope data: {e}")

        # Update other sensor data
        self.spo2_label.setText(f"SpO2: {self.data_manager.spo2_data}%")
        self.heart_rate_label.setText(f"Heart Rate: {self.data_manager.heart_rate_data} BPM")
        self.temp_label.setText(f"Temperature: {self.data_manager.temp_data} °C")
        self.hearttemp_label.setText(f"Heart Temperature: {self.data_manager.hearttemp_data} °C")
        self.pedometer_label.setText(f"Steps Taken: {self.data_manager.pedometer_data}")  # Update pedometer data

        try:
            spo2 = float(self.data_manager.spo2_data) if self.data_manager.spo2_data != "N/A" else 0
            hr = float(self.data_manager.heart_rate_data) if self.data_manager.heart_rate_data != "N/A" else 0

            alarms = []
            if spo2 < self.data_manager.alarm_thresholds["spo2"]:
                alarms.append("Low SpO2")
            if hr < self.data_manager.alarm_thresholds["heart_rate_low"]:
                alarms.append("Low Heart Rate")
            if hr > self.data_manager.alarm_thresholds["heart_rate_high"]:
                alarms.append("High Heart Rate")

            self.alarm_label.setText("ALERTS: " + ", ".join(alarms) if alarms else "No Alarms")
            self.alarm_label.setAlignment(Qt.AlignCenter)

            if alarms:
                self.alarm_label.setStyleSheet("color: red; font-weight: bold;")
            else:
                self.alarm_label.setStyleSheet("")
        except ValueError:
            pass

        QTimer.singleShot(100, self.update_gui)  # Schedule the next update (every 100ms)

    def update_graphs(self):
        """Enhanced graph update method with linear acceleration"""
        if (self.data_manager.temp_data != "N/A" and 
            self.data_manager.hearttemp_data != "N/A" and 
            self.data_manager.heart_rate_data != "N/A" and 
            self.data_manager.spo2_data != "N/A"):
            
            timestamp = datetime.now()
            self.timestamps.append(timestamp)
            self.temp_values.append(float(self.data_manager.temp_data))
            self.hearttemp_values.append(float(self.data_manager.hearttemp_data))
            self.hr_values.append(float(self.data_manager.heart_rate_data))
            self.spo2_values.append(float(self.data_manager.spo2_data))

            # Limit to the last N data points
            max_points = self.data_manager.graph_data_points
            if len(self.timestamps) > max_points:
                self.timestamps = self.timestamps[-max_points:]
                self.temp_values = self.temp_values[-max_points:]
                self.hearttemp_values = self.hearttemp_values[-max_points:]
                self.hr_values = self.hr_values[-max_points:]
                self.spo2_values = self.spo2_values[-max_points:]

            # Update Temperature Graph
            self.line_temp.set_data(self.timestamps, self.temp_values)
            self.line_hearttemp.set_data(self.timestamps, self.hearttemp_values)
            
            # Auto-scale with some padding
            temp_min = min(min(self.temp_values), min(self.hearttemp_values)) - 0.5
            temp_max = max(max(self.temp_values), max(self.hearttemp_values)) + 0.5
            self.ax_temp.set_ylim(temp_min, temp_max)
            if len(self.timestamps) > 1:
                self.ax_temp.set_xlim(self.timestamps[0], self.timestamps[-1])
            else:
                single_time = self.timestamps[0]
                pad = timedelta(seconds=1)
                self.ax_temp.set_xlim(single_time - pad, single_time + pad)            
            
            # Update Heart Rate Graph
            self.line_hr.set_data(self.timestamps, self.hr_values)
            self.line_spo2.set_data(self.timestamps, self.spo2_values)
            
            # Auto-scale with different ranges for HR and SpO2
            hr_min, hr_max = min(self.hr_values)-5, max(self.hr_values)+5
            spo2_min, spo2_max = min(self.spo2_values)-2, max(self.spo2_values)+2
            
            self.ax_hr.set_ylim(hr_min, hr_max)
            self.ax_hr2.set_ylim(spo2_min, spo2_max)
            if len(self.timestamps) > 1:
                self.ax_hr.set_xlim(self.timestamps[0], self.timestamps[-1])
            else:
                single_time = self.timestamps[0]
                pad = timedelta(seconds=1)
                self.ax_hr.set_xlim(single_time - pad, single_time + pad)
            
            # Update Linear Acceleration Graph
            if self.data_manager.accel_data != "N/A":
                self.accel_values.append(self.data_manager.linear_accel)
                
                # Limit to the last N data points
                if len(self.accel_values) > max_points:
                    self.accel_values = self.accel_values[-max_points:]
                
                self.line_accel.set_data(self.timestamps[-len(self.accel_values):], self.accel_values)
                
                # Auto-scale with some padding
                if len(self.accel_values) > 0:
                    accel_min = min(self.accel_values) - 0.5
                    accel_max = max(self.accel_values) + 0.5
                    self.ax_accel.set_ylim(max(0, accel_min), accel_max)
                    
                    if len(self.timestamps) > 1:
                        self.ax_accel.set_xlim(self.timestamps[0], self.timestamps[-1])
                    else:
                        single_time = self.timestamps[0]
                        pad = timedelta(seconds=1)
                        self.ax_accel.set_xlim(single_time - pad, single_time + pad)
            
            # Update 3D Gyroscope Graph if data available
            if self.data_manager.gyro_data != "N/A":
                try:
                    gyro_data = self.data_manager.gyro_data
                    x_val = float(gyro_data.split("X: ")[1].split(",")[0])
                    y_val = float(gyro_data.split("Y: ")[1].split(",")[0])
                    z_val = float(gyro_data.split("Z: ")[1].split(",")[0])
                    
                    # Remove old arrows
                    self.arrow_x.remove()
                    self.arrow_y.remove()
                    self.arrow_z.remove()
                    
                    # Create new arrows with normalized length
                    max_val = max(abs(x_val), abs(y_val), abs(z_val), 1)
                    scale = 2/max_val
                    
                    self.arrow_x = self.ax_3d.quiver(0, 0, 0, x_val*scale, 0, 0, 
                                                    color='r', linewidth=2, 
                                                    arrow_length_ratio=0.2, label='X')
                    self.arrow_y = self.ax_3d.quiver(0, 0, 0, 0, y_val*scale, 0, 
                                                    color='g', linewidth=2, 
                                                    arrow_length_ratio=0.2, label='Y')
                    self.arrow_z = self.ax_3d.quiver(0, 0, 0, 0, 0, z_val*scale, 
                                                    color='b', linewidth=2, 
                                                    arrow_length_ratio=0.2, label='Z')
                    
                    # Set equal aspect ratio
                    self.ax_3d.set_xlim(-2, 2)
                    self.ax_3d.set_ylim(-2, 2)
                    self.ax_3d.set_zlim(-2, 2)
                    
                except Exception as e:
                    print(f"Error updating 3D graph: {e}")

            # Redraw all canvases
            self.canvas_temp.draw()
            self.canvas_hr.draw()
            self.canvas_accel.draw()
            self.canvas_3d.draw()

            # Apply visibility settings
            self.line_temp.set_visible(self.data_manager.visible_sensors["temp"])
            self.line_hearttemp.set_visible(self.data_manager.visible_sensors["hearttemp"])
            self.line_hr.set_visible(self.data_manager.visible_sensors["heart_rate"])
            self.line_spo2.set_visible(self.data_manager.visible_sensors["spo2"])

            # Apply colors
            self.line_temp.set_color(self.data_manager.graph_colors["temp"])
            self.line_hearttemp.set_color(self.data_manager.graph_colors["hearttemp"])
            self.line_hr.set_color(self.data_manager.graph_colors["hr"])
            self.line_spo2.set_color(self.data_manager.graph_colors["spo2"])

        QTimer.singleShot(1000, self.update_graphs)

    def event(self, event):
        """Override the event method to handle the question mark button click."""
        if event.type() == QEvent.EnterWhatsThisMode:
            self.show_mainhelp()
            return True
        return super().event(event)

    def show_mainhelp(self):
        """Display a help message for the window."""
        QMessageBox.information(self, "Help", "This is the Main Program window. Use this window to view real-time sensor data, calibrate sensors, and monitor health metrics.")

    def open_pop_out_window(self):
        """Open the pop-out window."""
        self.pop_out_window = PopOutWindow(self.data_manager, self)
        self.pop_out_window.show()
        
    def return_to_intro(self):
        """Return to the introductory window."""
        self.close()
        self.intro_window = IntroWindow(self.data_manager)
        self.intro_window.show()

class PopOutWindow(QDialog):
    def __init__(self, data_manager, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.setWindowTitle("Sensor Data Summary")
        self.setGeometry(100, 100, 800, 600)  # Larger size to accommodate horizontal layout
        
        # Set window flags to keep it always on top
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        
        # Main layout
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        # Button row at the top
        button_layout = QHBoxLayout()
        
        # Customise button
        self.customise_button = QPushButton("Customise")
        self.customise_button.clicked.connect(self.open_customise_dialog)
        button_layout.addWidget(self.customise_button)
        
        # Close button
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)
        
        main_layout.addLayout(button_layout)

        # Horizontal layout for sensor data
        self.sensor_data_layout = QHBoxLayout()
        self.sensor_data_layout.setSpacing(10)
        
        # Sensor data labels - store them in a dictionary for easy access
        self.sensor_labels = {
            "accel": QLabel("Accel:\nN/A"),
            "gyro": QLabel("Gyro:\nN/A"),
            "spo2": QLabel("SpO2:\nN/A%"),
            "heart_rate": QLabel("HR:\nN/A BPM"),
            "temp": QLabel("Temp:\nN/A °C"),
            "hearttemp": QLabel("Heart Temp:\nN/A °C"),
            "pedometer": QLabel("Steps:\nN/A")
        }
        
        # Style and add all labels to the horizontal layout initially
        for label in self.sensor_labels.values():
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("""
                QLabel {
                    border: 1px solid #555;
                    border-radius: 5px;
                    padding: 5px;
                    background: #0B2E33;
                    min-width: 80px;
                    font-size: 10px;
                }
            """)
            self.sensor_data_layout.addWidget(label)
        
        main_layout.addLayout(self.sensor_data_layout)

        # Store visibility state for sensors and graphs
        self.sensor_visibility = {
            "accel": True,
            "gyro": True,
            "spo2": True,
            "heart_rate": True,
            "temp": True,
            "hearttemp": True,
            "pedometer": True
        }
        
        self.graph_visibility = {
            "temperature": True,
            "heart_rate": True,
            "linear_accel": True
        }

        # Graph container
        self.graph_container = QVBoxLayout()
        main_layout.addLayout(self.graph_container)

        # Temperature graph
        self.temp_graph_widget = QWidget()
        self.temp_graph_layout = QVBoxLayout(self.temp_graph_widget)
        self.fig_temp = plt.figure(figsize=(6, 2))
        self.ax_temp = self.fig_temp.add_subplot(111)
        self.ax_temp.set_title("Temperature Data")
        self.ax_temp.set_xlabel("Time")
        self.ax_temp.set_ylabel("Temp (°C)")
        self.line_temp, = self.ax_temp.plot([], [], lw=2, label="Body Temp", color=self.data_manager.graph_colors["temp"])
        self.line_hearttemp, = self.ax_temp.plot([], [], lw=2, label="Heart Temp", color=self.data_manager.graph_colors["hearttemp"])
        self.ax_temp.legend()
        self.ax_temp.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        self.canvas_temp = FigureCanvas(self.fig_temp)
        self.temp_graph_layout.addWidget(self.canvas_temp)
        self.graph_container.addWidget(self.temp_graph_widget)

        # Heart rate graph
        self.hr_graph_widget = QWidget()
        self.hr_graph_layout = QVBoxLayout(self.hr_graph_widget)
        self.fig_hr = plt.figure(figsize=(6, 2))
        self.ax_hr = self.fig_hr.add_subplot(111)
        self.ax_hr.set_title("Heart Rate & SpO2")
        self.ax_hr.set_xlabel("Time")
        self.ax_hr.set_ylabel("Value")
        self.line_hr, = self.ax_hr.plot([], [], lw=2, label="HR (BPM)", color=self.data_manager.graph_colors["hr"])
        self.line_spo2, = self.ax_hr.plot([], [], lw=2, label="SpO2 (%)", color=self.data_manager.graph_colors["spo2"])
        self.ax_hr.legend()
        self.ax_hr.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        self.canvas_hr = FigureCanvas(self.fig_hr)
        self.hr_graph_layout.addWidget(self.canvas_hr)
        self.graph_container.addWidget(self.hr_graph_widget)

        # Linear acceleration graph
        self.accel_graph_widget = QWidget()
        self.accel_graph_layout = QVBoxLayout(self.accel_graph_widget)
        self.fig_accel = plt.figure(figsize=(6, 2))
        self.ax_accel = self.fig_accel.add_subplot(111)
        self.ax_accel.set_title("Linear Acceleration")
        self.ax_accel.set_xlabel("Time")
        self.ax_accel.set_ylabel("Accel (m/s²)")
        self.line_accel, = self.ax_accel.plot([], [], lw=2, color='orange')
        self.ax_accel.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        self.canvas_accel = FigureCanvas(self.fig_accel)
        self.accel_graph_layout.addWidget(self.canvas_accel)
        self.graph_container.addWidget(self.accel_graph_widget)
    
        # For all graphs in PopOutWindow
        self.fig_temp.subplots_adjust(left=0.15, right=0.95, top=0.9, bottom=0.2)
        self.fig_hr.subplots_adjust(left=0.15, right=0.85, top=0.9, bottom=0.2)
        self.fig_accel.subplots_adjust(left=0.15, right=0.95, top=0.9, bottom=0.2)
    
        # Data for the graphs
        self.timestamps = []
        self.temp_values = []
        self.hearttemp_values = []
        self.hr_values = []
        self.spo2_values = []
        self.accel_values = []

        # Start updating the GUI and graphs
        self.update_gui()
        self.update_graphs()
        
    def open_customise_dialog(self):
        """Open a dialog to customise which sensors and graphs are visible."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Customise Display")
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)
        layout = QVBoxLayout()
        
        # Sensor visibility section
        sensor_group = QGroupBox("Sensor Visibility")
        sensor_layout = QGridLayout()
        
        row, col = 0, 0
        for i, (sensor, visible) in enumerate(self.sensor_visibility.items()):
            cb = QCheckBox(sensor.replace("_", " ").title())
            cb.setChecked(visible)
            sensor_layout.addWidget(cb, row, col)
            col += 1
            if col > 2:  # 3 columns
                col = 0
                row += 1
        
        sensor_group.setLayout(sensor_layout)
        layout.addWidget(sensor_group)
        
        # Graph visibility section
        graph_group = QGroupBox("Graph Visibility")
        graph_layout = QVBoxLayout()
        
        self.temp_graph_cb = QCheckBox("Temperature Graph")
        self.temp_graph_cb.setChecked(self.graph_visibility["temperature"])
        graph_layout.addWidget(self.temp_graph_cb)
        
        self.hr_graph_cb = QCheckBox("Heart Rate Graph")
        self.hr_graph_cb.setChecked(self.graph_visibility["heart_rate"])
        graph_layout.addWidget(self.hr_graph_cb)
        
        # Add checkbox for linear acceleration graph
        self.accel_graph_cb = QCheckBox("Linear Acceleration Graph")
        self.accel_graph_cb.setChecked(self.graph_visibility["linear_accel"])
        graph_layout.addWidget(self.accel_graph_cb)
        
        graph_group.setLayout(graph_layout)
        layout.addWidget(graph_group)
        
        # OK and Cancel buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        dialog.setLayout(layout)
        
        if dialog.exec_() == QDialog.Accepted:
            # Update sensor visibility
            for i, (sensor, _) in enumerate(self.sensor_visibility.items()):
                cb = sensor_layout.itemAt(i).widget()
                self.sensor_visibility[sensor] = cb.isChecked()
                self.sensor_labels[sensor].setVisible(cb.isChecked())
            
            # Update graph visibility
            self.graph_visibility["temperature"] = self.temp_graph_cb.isChecked()
            self.graph_visibility["heart_rate"] = self.hr_graph_cb.isChecked()
            self.graph_visibility["linear_accel"] = self.accel_graph_cb.isChecked()
         
            self.temp_graph_widget.setVisible(self.graph_visibility["temperature"])
            self.hr_graph_widget.setVisible(self.graph_visibility["heart_rate"])
            self.accel_graph_widget.setVisible(self.graph_visibility["linear_accel"])

    def update_gui(self):
        """Update the GUI with the latest sensor data."""
        if self.data_manager.accel_data != "N/A" and self.sensor_visibility["accel"]:
            x, y, z = self.data_manager.accel_data.split("X: ")[1].split(",")
            self.sensor_labels["accel"].setText(f"Accel:\nX: {x.strip()}\nY: {y.split('Y: ')[1].strip()}\nZ: {z.split('Z: ')[1].strip()}")
        
        if self.data_manager.gyro_data != "N/A" and self.sensor_visibility["gyro"]:
            x, y, z = self.data_manager.gyro_data.split("X: ")[1].split(",")
            self.sensor_labels["gyro"].setText(f"Gyro:\nX: {x.strip()}\nY: {y.split('Y: ')[1].strip()}\nZ: {z.split('Z: ')[1].strip()}")
        
        if self.data_manager.spo2_data != "N/A" and self.sensor_visibility["spo2"]:
            self.sensor_labels["spo2"].setText(f"SpO2:\n{self.data_manager.spo2_data}%")
        
        if self.data_manager.heart_rate_data != "N/A" and self.sensor_visibility["heart_rate"]:
            self.sensor_labels["heart_rate"].setText(f"HR:\n{self.data_manager.heart_rate_data} BPM")
        
        if self.data_manager.temp_data != "N/A" and self.sensor_visibility["temp"]:
            self.sensor_labels["temp"].setText(f"Temp:\n{self.data_manager.temp_data} °C")
        
        if self.data_manager.hearttemp_data != "N/A" and self.sensor_visibility["hearttemp"]:
            self.sensor_labels["hearttemp"].setText(f"Heart Temp:\n{self.data_manager.hearttemp_data} °C")
        
        if self.data_manager.pedometer_data != "N/A" and self.sensor_visibility["pedometer"]:
            self.sensor_labels["pedometer"].setText(f"Steps:\n{self.data_manager.pedometer_data}")

        QTimer.singleShot(100, self.update_gui)

    def update_graphs(self):
        """Update the graphs with the latest data."""
        if (self.data_manager.temp_data != "N/A" and 
            self.data_manager.hearttemp_data != "N/A" and 
            self.data_manager.heart_rate_data != "N/A" and 
            self.data_manager.spo2_data != "N/A" and 
            self.data_manager.accel_data != "N/A"):
            
            timestamp = datetime.now()
            self.timestamps.append(timestamp)
            self.temp_values.append(float(self.data_manager.temp_data))
            self.hearttemp_values.append(float(self.data_manager.hearttemp_data))
            self.hr_values.append(float(self.data_manager.heart_rate_data))
            self.spo2_values.append(float(self.data_manager.spo2_data))
            self.accel_values.append(self.data_manager.linear_accel)


            # Limit to the last N data points
            max_points = self.data_manager.graph_data_points
            if len(self.timestamps) > max_points:
                self.timestamps = self.timestamps[-max_points:]
                self.temp_values = self.temp_values[-max_points:]
                self.hearttemp_values = self.hearttemp_values[-max_points:]
                self.hr_values = self.hr_values[-max_points:]
                self.spo2_values = self.spo2_values[-max_points:]
                self.accel_values = self.accel_values[-max_points:]

            # Update temperature graph if visible
            if self.graph_visibility["temperature"]:
                self.line_temp.set_data(self.timestamps, self.temp_values)
                self.line_hearttemp.set_data(self.timestamps, self.hearttemp_values)
                self.ax_temp.relim()
                self.ax_temp.autoscale_view()
                self.canvas_temp.draw()

            # Update heart rate graph if visible
            if self.graph_visibility["heart_rate"]:
                self.line_hr.set_data(self.timestamps, self.hr_values)
                self.line_spo2.set_data(self.timestamps, self.spo2_values)
                self.ax_hr.relim()
                self.ax_hr.autoscale_view()
                self.canvas_hr.draw()
                
            # Update acceleratipn graph
            if self.graph_visibility["linear_accel"]:
                self.line_accel.set_data(self.timestamps, self.accel_values)
                self.ax_accel.relim()
                self.ax_accel.autoscale_view()
                self.canvas_accel.draw()

        QTimer.singleShot(1000, self.update_graphs)
        
# Start the introductory window
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon('app_icon.png'))
    app.setStyle('Fusion')

    data_manager = SensorDataManager()
    intro_window = IntroWindow(data_manager)
    intro_window.show()
    sys.exit(app.exec_())