
/* Auto Shutter V1
 *  
 * == WILSON LAB ==
 * 
 * Created by: Johann Hemmer
 * 10/18/2026
 * 
 * Code to move stepper motor by a specific angle at
 * a given speed.
 * 
 * Used with an Arduino UNO R3 and an EasyDriver V4.4.
 * 
 * Usage:
 *  MOVE <angle>
 *  STOP
 *  SPEED <angular speed>
 */

const unsigned long BAUD_RATE = 115200; 
const char DEVICE_ID[] = "AUTO_SHUTTER_V1";

const int STEP_PIN = 2;
const int DIR_PIN = 3;

// Motor: 1.8 degrees/full step
// EasyDriver: 1/8 microstepping
const float STEPS_PER_DEGREE = 1600.0 / 360.0;

unsigned long stepInterval = 2000; // 500 microsteps/s
unsigned long lastStep = 0;
unsigned long pulseStart = 0;

long stepsRemaining = 0;
bool moving = false;
bool stepHigh = false;

void setup() {
  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);

  digitalWrite(STEP_PIN, LOW);
  Serial.begin(BAUD_RATE);
  Serial.println("READY");
}

void loop() {

  // Read serial commands
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if (cmd == "ID") {
      // Stable handshake used by host software for cross-platform discovery.
      Serial.println(DEVICE_ID);
    }

    else if (cmd.startsWith("MOVE ")) {
      float angle = cmd.substring(5).toFloat();

      // Round to nearest microstep
      long steps = round(abs(angle) * STEPS_PER_DEGREE);

      // Stop previous movement before starting new one
      digitalWrite(STEP_PIN, LOW);
      stepHigh = false;

      digitalWrite(DIR_PIN, angle >= 0 ? HIGH : LOW);

      stepsRemaining = steps;
      moving = steps > 0;
      lastStep = micros();

      Serial.println("MOVING");
    }

    else if (cmd == "STOP") {
      moving = false;
      stepsRemaining = 0;
      digitalWrite(STEP_PIN, LOW);
      stepHigh = false;
      Serial.println("STOPPED");
    }

    else if (cmd.startsWith("SPEED ")) {
      int speed = cmd.substring(6).toInt();

      if (speed >= 50 && speed <= 2000) {
        stepInterval = 1000000UL / speed;
        Serial.println("SPEED SET");
      }
      else {
        Serial.println("INVALID SPEED");
      }
    }
  }

  // Nonblocking motor movement
  if (moving) {
    unsigned long now = micros();

    if (stepHigh) {
      // End STEP pulse
      if (now - pulseStart >= 5) {
        digitalWrite(STEP_PIN, LOW);
        stepHigh = false;
      }
    }
    else if (now - lastStep >= stepInterval) {
      // Start next STEP pulse
      digitalWrite(STEP_PIN, HIGH);

      pulseStart = now;
      lastStep = now;
      stepHigh = true;

      stepsRemaining--;

      if (stepsRemaining <= 0) {
        moving = false;
      }
    }
  }

  // Finish final pulse even after movement ends
  if (stepHigh && micros() - pulseStart >= 5) {
    digitalWrite(STEP_PIN, LOW);
    stepHigh = false;

    if (!moving) {
      Serial.println("DONE");
    }
  }
}
