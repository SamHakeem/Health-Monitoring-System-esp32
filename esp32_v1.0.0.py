import asyncio
from bleak import BleakScanner, BleakClient
import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QPushButton, QVBoxLayout, QWidget, QListWidget,
    QMessageBox, QCheckBox, QColorDialog, QFileDialog, QDialog, QSpinBox, QLineEdit,
    QHBoxLayout, QTextEdit, QGraphicsView, QGraphicsScene
)
from PyQt5.QtCore import Qt, QTimer, QDateTime
from PyQt5.QtGui import QPixmap, QImage, QIcon
import csv
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import winsound
import os
import threading

# Define UUIDs (must match those in the ESP32 code)
SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
ACCEL_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
GYRO_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a9"
SPO2_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26aa"
HEART_RATE_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26ab"
TEMP_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26ac"
HEARTTEMP_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26af"  # New UUID for heart temperature

# ESP32 MAC Address
ESP32_ADDRESS = "10:06:1c:17:65:7e"  # Replace with your ESP32's MAC address

# Global variables for sensor data
accel_data = "N/A"
gyro_data = "N/A"
spo2_data = "N/A"
heart_rate_data = "N/A"
temp_data = "N/A"
hearttemp_data = "N/A"  # New variable for heart temperature data

# New global variables for customization
visible_sensors = {
    "accel": True,
    "gyro": True,
    "spo2": True,
    "heart_rate": True,
    "temp": True,
    "hearttemp": True
}

graph_colors = {
    "temp": "blue",
    "hearttemp": "red",
    "hr": "green",
    "spo2": "purple"
}

alarm_thresholds = {
    "spo2": 90,
    "heart_rate_low": 60,
    "heart_rate_high": 100
}

# Global flag to control the BLE loop
running = True

# Data logging setup
LOG_FILE = "sensor_data.csv"

# Program version
PROGRAM_VERSION = "1.0.0"

# Global variable to track BLE connection status
ble_connected = False


# Settings Window
class SettingsWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setGeometry(200, 200, 400, 400)
        layout = QVBoxLayout()

        # Age input
        self.age_label = QLabel("Age:")
        self.age_entry = QLineEdit()
        layout.addWidget(self.age_label)
        layout.addWidget(self.age_entry)

        # Weight input
        self.weight_label = QLabel("Weight (kg):")
        self.weight_entry = QLineEdit()
        layout.addWidget(self.weight_label)
        layout.addWidget(self.weight_entry)

        # Alarm thresholds
        self.spo2_threshold = QSpinBox()
        self.spo2_threshold.setValue(alarm_thresholds["spo2"])
        self.spo2_threshold.setRange(0, 100)
        layout.addWidget(QLabel("SpO2 Alarm Threshold (%)"))
        layout.addWidget(self.spo2_threshold)

        # Data directory selection
        self.path_button = QPushButton("Select Data Directory")
        self.path_button.clicked.connect(self.select_directory)
        layout.addWidget(self.path_button)

        # Clear data button
        self.clear_button = QPushButton("Clear Data")
        self.clear_button.clicked.connect(self.clear_data)
        layout.addWidget(self.clear_button)

        self.setLayout(layout)

    def select_directory(self):
        global LOG_FILE
        path = QFileDialog.getExistingDirectory(self, "Select Directory")
        if path:
            LOG_FILE = os.path.join(path, "sensor_data.csv")
            QMessageBox.information(self, "Success", f"Data will be saved to: {LOG_FILE}")

    def clear_data(self):
        with open(LOG_FILE, "w") as f:
            f.write("")
        QMessageBox.information(self, "Success", "Data cleared successfully")

    def accept(self):
        global LOG_FILE
        alarm_thresholds["spo2"] = self.spo2_threshold.value()
        super().accept()


# Customise Window
class CustomiseWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Customise")
        self.setGeometry(200, 200, 400, 400)
        layout = QVBoxLayout()

        # Sensor visibility checkboxes
        self.checkboxes = {}
        for sensor in visible_sensors:
            cb = QCheckBox(sensor.replace("_", " ").title())
            cb.setChecked(visible_sensors[sensor])
            self.checkboxes[sensor] = cb
            layout.addWidget(cb)

        # Color pickers
        self.color_buttons = {}
        for graph in graph_colors:
            btn = QPushButton(f"Choose {graph.title()} Color")
            btn.clicked.connect(lambda _, g=graph: self.choose_color(g))
            layout.addWidget(btn)
            self.color_buttons[graph] = btn

        self.setLayout(layout)

    def choose_color(self, graph):
        color = QColorDialog.getColor()
        if color.isValid():
            graph_colors[graph] = color.name()
            self.sender().setStyleSheet(f"background-color: {color.name()}")


# Function to log sensor data
def log_data(timestamp, accel, gyro, spo2, heart_rate, temp, hearttemp):
    """Log sensor data to a CSV file."""
    with open(LOG_FILE, mode="a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([timestamp, accel, gyro, spo2, heart_rate, temp, hearttemp])


# Function to play a sound
def play_sound(filename):
    if os.path.exists(filename):
        if os.name == "nt":  # Windows
            winsound.PlaySound(filename, winsound.SND_ASYNC)
        else:  # macOS/Linux
            os.system(f"afplay {filename} &")
    else:
        print(f"Warning: Sound file '{filename}' not found.")


# Callback function to update sensor data
def update_sensor_data(sensor_type, data):
    global accel_data, gyro_data, spo2_data, heart_rate_data, temp_data, hearttemp_data
    value = data.decode("utf-8")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if sensor_type == "accel":
        x, y, z = value.split(',')
        accel_data = f"X: {x}, Y: {y}, Z: {z}"
        log_data(timestamp, value, gyro_data, spo2_data, heart_rate_data, temp_data, hearttemp_data)
    elif sensor_type == "gyro":
        x, y, z = value.split(',')
        gyro_data = f"X: {x}, Y: {y}, Z: {z}"
        log_data(timestamp, accel_data, value, spo2_data, heart_rate_data, temp_data, hearttemp_data)
    elif sensor_type == "spo2":
        spo2_data = value
        log_data(timestamp, accel_data, gyro_data, value, heart_rate_data, temp_data, hearttemp_data)
    elif sensor_type == "heart_rate":
        heart_rate_data = value
        log_data(timestamp, accel_data, gyro_data, spo2_data, value, temp_data, hearttemp_data)
    elif sensor_type == "temp":
        temp_data = value
        log_data(timestamp, accel_data, gyro_data, spo2_data, heart_rate_data, value, hearttemp_data)
    elif sensor_type == "hearttemp":  # Handle heart temperature data
        hearttemp_data = value
        log_data(timestamp, accel_data, gyro_data, spo2_data, heart_rate_data, temp_data, value)


# Async function to connect to the ESP32 and read data
async def read_ble_data(address):
    global running, ble_connected
    while running:
        try:
            async with BleakClient(address) as client:
                print(f"Connected to {address}")
                ble_connected = True
                intro_window.update_connection_status(ble_connected)
                if hasattr(intro_window, 'connect_window'):
                    intro_window.connect_window.close()  # Close the connect window after successful connection

                # Enable notifications for all characteristics
                await client.start_notify(ACCEL_UUID, lambda _, data: update_sensor_data("accel", data))
                await client.start_notify(GYRO_UUID, lambda _, data: update_sensor_data("gyro", data))
                await client.start_notify(SPO2_UUID, lambda _, data: update_sensor_data("spo2", data))
                await client.start_notify(HEART_RATE_UUID, lambda _, data: update_sensor_data("heart_rate", data))
                await client.start_notify(TEMP_UUID, lambda _, data: update_sensor_data("temp", data))
                await client.start_notify(HEARTTEMP_UUID, lambda _, data: update_sensor_data("hearttemp", data))  # Heart temperature notifications

                print("Notifications enabled. Waiting for updates...")
                while running:
                    await asyncio.sleep(0.1)  # Keep the connection alive
        except Exception as e:
            print(f"BLE connection error: {e}. Retrying in 5 seconds...")
            ble_connected = False
            intro_window.update_connection_status(ble_connected)
            if main_program_window and main_program_window.isVisible():
                QMessageBox.critical(main_program_window, "Disconnected", "Bluetooth device disconnected. Please reconnect.")
                main_program_window.return_to_intro()
            await asyncio.sleep(5)


# Introductory Window
class IntroWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Health Monitoring System")
        self.setGeometry(100, 100, 600, 400)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.layout = QVBoxLayout(self.central_widget)

        # Program version label
        self.version_label = QLabel(f"Version: {PROGRAM_VERSION}")
        self.version_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self.layout.addWidget(self.version_label)

        # Main label (centered)
        self.main_label = QLabel("Health Monitoring System")
        self.main_label.setStyleSheet("font-size: 20px; font-weight: bold;")
        self.main_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.main_label)

        # Buttons
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.open_connect_window)
        self.layout.addWidget(self.connect_button)

        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.open_settings_window)
        self.layout.addWidget(self.settings_button)

        self.customise_button = QPushButton("Customise")
        self.customise_button.clicked.connect(self.open_customise_window)
        self.layout.addWidget(self.customise_button)

        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.start_program)
        self.layout.addWidget(self.start_button)

        # Connection status label (centered)
        self.connection_status = QLabel("Device: Not Connected")
        self.connection_status.setStyleSheet("font-size: 12px;")
        self.connection_status.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.connection_status)

    def update_connection_status(self, connected):
        """Update the connection status label."""
        status = "Connected" if connected else "Not Connected"
        self.connection_status.setText(f"Device: {status}")

    def open_connect_window(self):
        """Open the Connect window to scan and pair with BLE devices."""
        self.connect_window = QDialog(self)
        self.connect_window.setWindowTitle("Connect")
        self.connect_window.setGeometry(200, 200, 400, 300)

        self.connect_layout = QVBoxLayout(self.connect_window)

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
        threading.Thread(target=asyncio.run, args=(read_ble_data(device_address),), daemon=True).start()

    def open_settings_window(self):
        """Open the Settings window to input age, weight, and clear data."""
        self.settings_window = SettingsWindow()
        if self.settings_window.exec_():
            # Update alarm thresholds
            alarm_thresholds["spo2"] = self.settings_window.spo2_threshold.value()

    def clear_data(self):
        """Clear saved data."""
        with open(LOG_FILE, "w") as file:
            file.write("")  # Clear the file
        print("Data cleared.")

    def open_customise_window(self):
        """Open the Customise window to change data presentation."""
        self.customise_window = CustomiseWindow()
        if self.customise_window.exec_():
            # Save settings
            for sensor, cb in self.customise_window.checkboxes.items():
                visible_sensors[sensor] = cb.isChecked()

    def start_program(self):
        """Start the main program."""
        if not ble_connected:
            QMessageBox.critical(self, "Error", "Please connect to a device first!")
            return
        self.close()  # Close the introductory window
        global main_program_window
        main_program_window = MainProgram()
        main_program_window.show()


# Main Program
class MainProgram(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ESP32 Sensor Monitor")
        self.setGeometry(100, 100, 1000, 800)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.layout = QVBoxLayout(self.central_widget)

        # Labels for displaying sensor data
        self.accel_label = QLabel("Accelerometer: N/A")
        self.layout.addWidget(self.accel_label)

        self.gyro_label = QLabel("Gyroscope: N/A")
        self.layout.addWidget(self.gyro_label)

        self.spo2_label = QLabel("SpO2: N/A%")
        self.layout.addWidget(self.spo2_label)

        self.heart_rate_label = QLabel("Heart Rate: N/A BPM")
        self.layout.addWidget(self.heart_rate_label)

        self.temp_label = QLabel("Temperature: N/A °C")
        self.layout.addWidget(self.temp_label)

        self.hearttemp_label = QLabel("Heart Temperature: N/A °C")
        self.layout.addWidget(self.hearttemp_label)

        self.alarm_label = QLabel("No Alarms")
        self.layout.addWidget(self.alarm_label)

        # Matplotlib graph for real-time temperature data
        self.fig_temp, self.ax_temp = plt.subplots(figsize=(6, 4))
        self.ax_temp.set_title("Real-Time Temperature Data", fontsize=12)
        self.ax_temp.set_xlabel("Time", fontsize=10)
        self.ax_temp.set_ylabel("Temperature (°C)", fontsize=10)
        self.line_temp, = self.ax_temp.plot([], [], lw=2, label="Body Temperature")
        self.line_hearttemp, = self.ax_temp.plot([], [], lw=2, label="Heart Temperature")
        self.ax_temp.legend()
        self.canvas_temp = FigureCanvas(self.fig_temp)
        self.layout.addWidget(self.canvas_temp)

        # Matplotlib graph for real-time heart rate and SpO2 data
        self.fig_hr, self.ax_hr = plt.subplots(figsize=(6, 4))
        self.ax_hr.set_title("Real-Time Heart Rate and SpO2", fontsize=12)
        self.ax_hr.set_xlabel("Time", fontsize=10)
        self.ax_hr.set_ylabel("Value", fontsize=10)
        self.line_hr, = self.ax_hr.plot([], [], lw=2, label="Heart Rate (BPM)")
        self.line_spo2, = self.ax_hr.plot([], [], lw=2, label="SpO2 (%)")
        self.ax_hr.legend()
        self.canvas_hr = FigureCanvas(self.fig_hr)
        self.layout.addWidget(self.canvas_hr)

        # Data for the graphs
        self.timestamps = []
        self.temp_values = []
        self.hearttemp_values = []
        self.hr_values = []
        self.spo2_values = []

        # Return to Intro button
        self.return_button = QPushButton("Return to Intro")
        self.return_button.clicked.connect(self.return_to_intro)
        self.layout.addWidget(self.return_button)

        # Start updating the GUI and graphs
        self.update_gui()
        self.update_graphs()

    def update_gui(self):
        global accel_data, gyro_data, spo2_data, heart_rate_data, temp_data, hearttemp_data
        self.accel_label.setText(f"Accelerometer: {accel_data}")
        self.gyro_label.setText(f"Gyroscope: {gyro_data}")
        self.spo2_label.setText(f"SpO2: {spo2_data}%")
        self.heart_rate_label.setText(f"Heart Rate: {heart_rate_data} BPM")
        self.temp_label.setText(f"Temperature: {temp_data} °C")
        self.hearttemp_label.setText(f"Heart Temperature: {hearttemp_data} °C")

        try:
            spo2 = float(spo2_data) if spo2_data != "N/A" else 0
            hr = float(heart_rate_data) if heart_rate_data != "N/A" else 0

            alarms = []
            if spo2 < alarm_thresholds["spo2"]:
                alarms.append("Low SpO2")
                play_sound("alarm.wav")
            if hr < alarm_thresholds["heart_rate_low"]:
                alarms.append("Low Heart Rate")
                play_sound("alarm.wav")
            if hr > alarm_thresholds["heart_rate_high"]:
                alarms.append("High Heart Rate")
                play_sound("alarm.wav")

            self.alarm_label.setText("ALERTS: " + ", ".join(alarms) if alarms else "No Alarms")
        except ValueError:
            pass

        QTimer.singleShot(100, self.update_gui)  # Schedule the next update (every 100ms)

    def update_graphs(self):
        global timestamps, temp_values, hearttemp_values, hr_values, spo2_values
        if temp_data != "N/A" and hearttemp_data != "N/A" and heart_rate_data != "N/A" and spo2_data != "N/A":
            # Convert the current time to a datetime object
            timestamp = datetime.now()
            self.timestamps.append(timestamp)
            self.temp_values.append(float(temp_data))
            self.hearttemp_values.append(float(hearttemp_data))
            self.hr_values.append(float(heart_rate_data))
            self.spo2_values.append(float(spo2_data))

            # Limit to the last 10 data points
            if len(self.timestamps) > 10:
                self.timestamps.pop(0)
                self.temp_values.pop(0)
                self.hearttemp_values.pop(0)
                self.hr_values.pop(0)
                self.spo2_values.pop(0)

            # Update the temperature graph
            self.line_temp.set_data(self.timestamps, self.temp_values)
            self.line_hearttemp.set_data(self.timestamps, self.hearttemp_values)
            self.ax_temp.relim()
            self.ax_temp.autoscale_view()
            self.canvas_temp.draw()

            # Update the heart rate and SpO2 graph
            self.line_hr.set_data(self.timestamps, self.hr_values)
            self.line_spo2.set_data(self.timestamps, self.spo2_values)
            self.ax_hr.relim()
            self.ax_hr.autoscale_view()
            self.canvas_hr.draw()

            # Apply visibility settings
            self.line_temp.set_visible(visible_sensors["temp"])
            self.line_hearttemp.set_visible(visible_sensors["hearttemp"])
            self.line_hr.set_visible(visible_sensors["heart_rate"])
            self.line_spo2.set_visible(visible_sensors["spo2"])

            # Apply colors
            self.line_temp.set_color(graph_colors["temp"])
            self.line_hearttemp.set_color(graph_colors["hearttemp"])
            self.line_hr.set_color(graph_colors["hr"])
            self.line_spo2.set_color(graph_colors["spo2"])

        QTimer.singleShot(1000, self.update_graphs)

    def return_to_intro(self):
        """Return to the introductory window."""
        self.close()
        self.intro_window = IntroWindow()
        self.intro_window.show()


# Start the introductory window
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon('app_icon.png'))

    intro_window = IntroWindow()
    intro_window.show()
    sys.exit(app.exec_())