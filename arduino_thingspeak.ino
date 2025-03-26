#include <Wire.h>
#include "LSM6DS3-SOLDERED.h"
#include "DFRobot_BloodOxygen_S.h"
#include <Adafruit_TMP117.h>
#include <NimBLEDevice.h>
#include <WiFi.h>
#include <HTTPClient.h>

// WiFi credentials
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";

// ThingSpeak settings
const char* thingspeakServer = "api.thingspeak.com";
const String apiKey = "M441LEYBB2OFZKM2";
const unsigned long channelID = 2893826;

// IMU (Gyroscope & Accelerometer)
Soldered_LSM6DS3 myIMU;

// Heart Rate & SpO2 Sensor
#define I2C_ADDRESS 0x57
DFRobot_BloodOxygen_S_I2C MAX30102(&Wire, I2C_ADDRESS);

// Temperature Sensor
Adafruit_TMP117 tmp117;

// BLE Service and Characteristics UUIDs
#define SERVICE_UUID "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define ACCEL_UUID "beb5483e-36e1-4688-b7f5-ea07361b26a8"
#define GYRO_UUID "beb5483e-36e1-4688-b7f5-ea07361b26a9"
#define SPO2_UUID "beb5483e-36e1-4688-b7f5-ea07361b26aa"
#define HEART_RATE_UUID "beb5483e-36e1-4688-b7f5-ea07361b26ab"
#define TEMP_UUID "beb5483e-36e1-4688-b7f5-ea07361b26ac"
#define HEARTTEMP_UUID "beb5483e-36e1-4688-b7f5-ea07361b26af"
#define PEDOMETER_UUID "beb5483e-36e1-4688-b7f5-ea07361b26b0"

// BLE Characteristics
BLECharacteristic *accelCharacteristic;
BLECharacteristic *gyroCharacteristic;
BLECharacteristic *spo2Characteristic;
BLECharacteristic *heartRateCharacteristic;
BLECharacteristic *tempCharacteristic;
BLECharacteristic *heartTempCharacteristic;
BLECharacteristic *pedometerCharacteristic;

// Custom server callbacks class
class MyServerCallbacks : public NimBLEServerCallbacks {
  void onDisconnect(NimBLEServer *pServer) {
    NimBLEDevice::startAdvertising();
    Serial.println("Client disconnected. Restarting advertising...");
  }
};

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("Initializing sensors and WiFi...");

  // Connect to WiFi
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("");
  Serial.println("WiFi connected");
  Serial.println("IP address: ");
  Serial.println(WiFi.localIP());

  // Initialize IMU
  if (myIMU.begin() != 0) {
    Serial.println("Failed to initialize IMU!");
  } else {
    Serial.println("IMU initialized successfully.");
  }

  // Initialize Heart Rate & SpO2 Sensor
  if (!MAX30102.begin()) {
    Serial.println("Failed to initialize MAX30102!");
  } else {
    Serial.println("MAX30102 initialized successfully.");
    MAX30102.sensorStartCollect();
  }

  // Initialize Temperature Sensor
  if (!tmp117.begin()) {
    Serial.println("Failed to find TMP117 chip!");
  } else {
    Serial.println("TMP117 initialized successfully.");
  }

  // Initialize BLE
  NimBLEDevice::init("ESP32_BLE_Server");

  NimBLEServer *pServer = NimBLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());
  NimBLEService *pService = pServer->createService(SERVICE_UUID);

  // BLE Characteristics
  accelCharacteristic = pService->createCharacteristic(
    ACCEL_UUID,
    NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);

  gyroCharacteristic = pService->createCharacteristic(
    GYRO_UUID,
    NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);

  spo2Characteristic = pService->createCharacteristic(
    SPO2_UUID,
    NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);

  heartRateCharacteristic = pService->createCharacteristic(
    HEART_RATE_UUID,
    NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);

  tempCharacteristic = pService->createCharacteristic(
    TEMP_UUID,
    NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);

  heartTempCharacteristic = pService->createCharacteristic(
    HEARTTEMP_UUID,
    NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);

  pedometerCharacteristic = pService->createCharacteristic(
    PEDOMETER_UUID,
    NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);

  // Service Advertising
  pService->start();
  NimBLEAdvertising *pAdvertising = NimBLEDevice::getAdvertising();
  pAdvertising->setName("ESP32_BLE_Server");
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->setMinInterval(100);
  pAdvertising->setMaxInterval(150);
  pAdvertising->start();
  Serial.println("BLE Server started");

  // Initialize pedometer
  uint8_t errorAccumulator = 0;
  uint8_t dataToWrite = 0;

  // Setup the accelerometer
  dataToWrite |= LSM6DS3_ACC_GYRO_FS_XL_2g;
  dataToWrite |= LSM6DS3_ACC_GYRO_ODR_XL_26Hz;
  errorAccumulator += myIMU.writeRegister(LSM6DS3_ACC_GYRO_CTRL1_XL, dataToWrite);

  // Enable embedded functions -- ALSO clears the pedometer step count
  errorAccumulator += myIMU.writeRegister(LSM6DS3_ACC_GYRO_CTRL10_C, 0x3E);
  // Enable pedometer algorithm
  errorAccumulator += myIMU.writeRegister(LSM6DS3_ACC_GYRO_TAP_CFG1, 0x40);
  // Step Detector interrupt driven to INT1 pin
  errorAccumulator += myIMU.writeRegister(LSM6DS3_ACC_GYRO_INT1_CTRL, 0x10);

  if (errorAccumulator) {
    Serial.println("Problem configuring the device.");
    while (1) {
      delay(100);
    }
  } else {
    Serial.println("Pedometer initialized successfully.");
  }
}

void sendToThingSpeak(float field1, float field2, float field3, float field4, float field5, float field6, float field7) {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    
    String url = "http://" + String(thingspeakServer) + "/update?api_key=" + apiKey + 
                 "&field1=" + String(field1) +
                 "&field2=" + String(field2) +
                 "&field3=" + String(field3) +
                 "&field4=" + String(field4) +
                 "&field5=" + String(field5) +
                 "&field6=" + String(field6) +
                 "&field7=" + String(field7);
    
    http.begin(url);
    int httpResponseCode = http.GET();
    
    if (httpResponseCode > 0) {
      Serial.print("ThingSpeak HTTP Response code: ");
      Serial.println(httpResponseCode);
    } else {
      Serial.print("Error sending to ThingSpeak: ");
      Serial.println(httpResponseCode);
    }
    
    http.end();
  } else {
    Serial.println("WiFi not connected - can't send to ThingSpeak");
  }
}

void loop() {
  // Read heart rate and SpO2 first to check if they're valid
  MAX30102.getHeartbeatSPO2();
  float spo2 = MAX30102._sHeartbeatSPO2.SPO2;
  float heartRate = MAX30102._sHeartbeatSPO2.Heartbeat;
  
  // Skip this iteration if either heart rate or SpO2 is -1
  if (heartRate == -1 || spo2 == -1) {
    Serial.println("Invalid sensor reading - skipping this iteration. Check sensor positioning.");
    delay(1000);
    return;
  }

  // If we get here, we have valid heart rate and SpO2 values
  float heartTemp = MAX30102.getTemperature_C();

  // Read and prepare other sensor data
  float accelX = myIMU.readFloatAccelX();
  float accelY = myIMU.readFloatAccelY();
  float accelZ = myIMU.readFloatAccelZ();
  String accelData = String(accelX, 4) + "," + String(accelY, 4) + "," + String(accelZ, 4);
  
  float gyroX = myIMU.readFloatGyroX();
  float gyroY = myIMU.readFloatGyroY();
  float gyroZ = myIMU.readFloatGyroZ();
  String gyroData = String(gyroX, 4) + "," + String(gyroY, 4) + "," + String(gyroZ, 4);

  sensors_event_t tempEvent;
  tmp117.getEvent(&tempEvent);
  float temperature = tempEvent.temperature;

  // Read pedometer data
  uint8_t readDataByte = 0;
  uint16_t stepsTaken = 0;
  myIMU.readRegister(&readDataByte, LSM6DS3_ACC_GYRO_STEP_COUNTER_H);
  stepsTaken = ((uint16_t)readDataByte) << 8;
  myIMU.readRegister(&readDataByte, LSM6DS3_ACC_GYRO_STEP_COUNTER_L);
  stepsTaken |= readDataByte;

  // Update BLE characteristics
  accelCharacteristic->setValue(accelData.c_str());
  accelCharacteristic->notify();

  gyroCharacteristic->setValue(gyroData.c_str());
  gyroCharacteristic->notify();

  spo2Characteristic->setValue(String(spo2).c_str());
  spo2Characteristic->notify();

  heartRateCharacteristic->setValue(String(heartRate).c_str());
  heartRateCharacteristic->notify();

  tempCharacteristic->setValue(String(temperature).c_str());
  tempCharacteristic->notify();

  heartTempCharacteristic->setValue(String(heartTemp).c_str());
  heartTempCharacteristic->notify();

  pedometerCharacteristic->setValue(String(stepsTaken).c_str());
  pedometerCharacteristic->notify();

  // Send data to ThingSpeak
  // Field mapping:
  // field1: Heart Rate (BPM)
  // field2: SpO2 (%)
  // field3: Body Temperature (℃)
  // field4: Heart Sensor Temperature (℃)
  // field5: Steps Taken
  // field6: Accelerometer X (g)
  // field7: Gyroscope X (dps)
  sendToThingSpeak(heartRate, spo2, temperature, heartTemp, stepsTaken, accelX, gyroX);

  // Print sensor data to Serial for debugging
  Serial.println("\nSensor Readings:");
  Serial.println("Accelerometer: " + accelData);
  Serial.println("Gyroscope: " + gyroData);
  Serial.println("SPO2: " + String(spo2) + "%");
  Serial.println("Heart Rate: " + String(heartRate) + " BPM");
  Serial.println("Temperature: " + String(temperature) + " ℃");
  Serial.println("HeartTemperature: " + String(heartTemp) + " ℃");
  Serial.println("Steps Taken: " + String(stepsTaken));
  Serial.println();

  delay(15000); // ThingSpeak requires at least 15 seconds between updates for free account
}
