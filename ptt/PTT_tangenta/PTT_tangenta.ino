unsigned long lastKeepAliveTime = 0;
const unsigned long keepAliveInterval = 1000; // 1 секунда
bool lastButtonState = HIGH; // Кнопка подключена с PULLUP, поэтому HIGH - не нажата

void setup() {
  Serial.begin(57600);
  pinMode(9, INPUT_PULLUP);
}

void loop() {
  bool currentButtonState = digitalRead(9);

  // Обработка нажатия/отпускания кнопки
  if (currentButtonState != lastButtonState) {
    // Защита от дребезга (ждем небольшое время)
    delay(30);
    currentButtonState = digitalRead(9); // Повторно считываем состояние
    
    if (currentButtonState != lastButtonState) {
      if (currentButtonState == LOW) {
        sendPttCommand("PRESSED");
      } else {
        sendPttCommand("RELEASED");
      }
      lastButtonState = currentButtonState;
    }
  }

  // Отправка keep-alive раз в секунду
  unsigned long currentTime = millis();
  if (currentTime - lastKeepAliveTime >= keepAliveInterval) {
    sendKeepAlive();
    lastKeepAliveTime = currentTime;
  }
}

void sendPttCommand(const char* state) {
  String xml = String() + 
    "<map>" +
    "<entry><string>BUTTON</string><string>PTT</string></entry>" +
    "<entry><string>STATE</string><string>" + state + "</string></entry>" +
    "</map>";
  
  Serial.println(xml);
}

void sendKeepAlive() {
  String xml = String() + 
    "<map>" +
    "<entry><string>KEEP_ALIVE</string><string>1</string></entry>" +
    "</map>";
  
  Serial.println(xml);
}