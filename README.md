#  Health Monitoring System (ESP32-Based)

A customisable, open-source wearable system designed to monitor physical activity and vital signs in real time using the Arduino Nano ESP32 and various biomedical sensors. This project integrates embedded firmware with a Python desktop application via Bluetooth Low Energy (BLE) for seamless data visualization and analysis.

---

##  Features

- Real-time health monitoring via BLE
- Modular sensor support:
  - Heart rate & SpO₂ (MAX30102)
  - Body temperature (TMP117)
  - Motion (LSM6DSOx accelerometer + gyroscope)
  - Step count (basic pedometer logic)
- Cross-platform desktop GUI built with PyQt5
- Clean and extendable codebase for student projects, prototypes, and research

---

##  Motivation

Designed as a final-year project for Electrical and Computer Engineering, this system demonstrates how open-source hardware and software can be used to develop affordable, customizable wearable health solutions. Inspired by commercial products like Fitbit and Apple Watch but focused on flexibility and learning.

---

##  Hardware Used

| Component        | Model             |
|------------------|-------------------|
| Microcontroller  | Arduino Nano ESP32 |
| Heart Sensor     | MAX30102          |
| Motion Sensor    | LSM6DSOx          |
| Temp Sensor      | TMP117            |
| Power Supply     | LiPo Battery (3.7V) |

> Sensor use is configurable and adaptable based on available modules.

---

##  Software Overview

- **Firmware**: Arduino C++ code running on ESP32, collecting sensor data and broadcasting via BLE
- **Desktop App**: Python + PyQt5 GUI that connects via BLE, reads sensor values, and visualizes them in real time

---

##  Folder Structure

```plaintext
Health-Monitoring-System-esp32/
├── firmware/           # ESP32 Arduino code
│   └── main.ino
├── desktop-app/        # Python PyQt5 GUI application
│   ├── main.py
│   └── ui/             # UI resources, icons, etc.
├── assets/             # Diagrams, screenshots, GIFs
├── docs/               # Technical documentation, schematics
├── requirements.txt    # Python dependencies
├── .gitignore
├── LICENSE
└── README.md
```

##  Setup Instructions

###  Prerequisites

- Arduino IDE with ESP32 board support  
- Python 3.8+  
- Bluetooth-enabled PC or USB BLE dongle  

---

###  Firmware Upload

1. Open `firmware/main.ino` in Arduino IDE  
2. Select **Arduino Nano ESP32** as the board  
3. Connect board via USB and upload the code  

---

### 💻 Desktop App Setup

```bash
cd desktop-app
pip install -r ../requirements.txt
python main.py
