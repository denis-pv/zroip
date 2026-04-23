# zROIP project


## [server](https://github.com/denis-pv/zroip/tree/main/rcont)

скрипт серверной части

## [сlient](https://github.com/denis-pv/zroip/tree/main/client) 

Клиент для zroip server

## [rcont.py](https://github.com/denis-pv/zroip/tree/main/client)

Скрипт мониторинга сервера

## [PTT](https://github.com/denis-pv/zroip/tree/main/server)

Пример кода устройства PTT для ардуино.

### Как это работает

- Ардуино подключено к ПК как usb-com, к ней подключена кнопка тангенты на ногу D9.
- Кнопка замыкает пин на землю.
- Ардуино через usb COM отправляет комманду что кнопка PTT нажата.
- скрипт, zroip_client.py подключен к этому COM порту, и видит комманду, встает на передачу голоса.
- Когда на ардуино кнопка отпущена, она отсылает комманду о том что кнопка PTT отжата.
- Скрипт завершает передачу голоса на сервер.


