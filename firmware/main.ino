#include <Wire.h>
#include "LSM6DS3-SOLDERED.h"
#include "DFRobot_BloodOxygen_S.h"
#include <Adafruit_TMP117.h>
#include <NimBLEDevice.h>

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
BLECharacteristic *pedometerCharacteristic;  // New characteristic for pedometer

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
  Serial.println("Initializing sensors...");

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
  NimBLEDevice::init("ESP32_BLE_Server");  //base device name

  NimBLEServer *pServer = NimBLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());  //disconnect callback
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
    NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);  // New characteristic for pedometer

  // Service Advertising
  pService->start();
  NimBLEAdvertising *pAdvertising = NimBLEDevice::getAdvertising();
  pAdvertising->setName("ESP32_BLE_Server");  //name during scanning
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->setMinInterval(100);
  pAdvertising->setMaxInterval(150);
  pAdvertising->start();
  Serial.println("BLE Server started");

  NimBLEAddress macAddress = NimBLEDevice::getAddress();
  Serial.print("Bluetooth MAC Address: "); //just for testing
  Serial.println(macAddress.toString().c_str());

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

void loop() {
  // Read heart rate and SpO2 first to check if they're valid
  MAX30102.getHeartbeatSPO2();
  float spo2 = MAX30102._sHeartbeatSPO2.SPO2;
  float heartRate = MAX30102._sHeartbeatSPO2.Heartbeat;
  
  // Skip this iteration if either heart rate or SpO2 is -1
  if (heartRate == -1 || spo2 == -1) {
    Serial.println("Invalid sensor reading - skipping this iteration. Check sensor positioning.");
    delay(1000); // Wait before trying again
    return; // Skip the rest of this loop iteration
  }

  // If we get here, we have valid heart rate and SpO2 values
  float heartTemp = MAX30102.getTemperature_C();

  // Read and prepare other sensor data
  String accelData = String(myIMU.readFloatAccelX(), 4) + "," + String(myIMU.readFloatAccelY(), 4) + "," + String(myIMU.readFloatAccelZ(), 4);
  String gyroData = String(myIMU.readFloatGyroX(), 4) + "," + String(myIMU.readFloatGyroY(), 4) + "," + String(myIMU.readFloatGyroZ(), 4);

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

  pedometerCharacteristic->setValue(String(stepsTaken).c_str());  // Update pedometer characteristic
  pedometerCharacteristic->notify();

  // Print sensor data to Serial for debugging
  Serial.println("\nSensor Readings:");
  Serial.println("Accelerometer: " + accelData);
  Serial.println("Gyroscope: " + gyroData);
  Serial.println("SPO2: " + String(spo2) + "%");
  Serial.println("Heart Rate: " + String(heartRate) + " BPM");
  Serial.println("Temperature: " + String(temperature) + " ℃");
  Serial.println("HeartTemperature: " + String(heartTemp) + " ℃");
  Serial.println("Steps Taken: " + String(stepsTaken));  // Print steps taken
  Serial.println();

  delay(1000);  // Update once per second
}
