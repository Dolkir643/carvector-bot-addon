# Установка CarVector Bot в Home Assistant OS (NUC)

## 1. Залить репозиторий add-on на GitHub

Если репозиторий `carvector-bot-addon` ещё не создан или нужно обновить код:

```bash
cd /Users/kirill/Desktop/addons
git init
git add repository.yaml README.md carvector_bot/
git commit -m "CarVector Bot add-on для HAOS"
git branch -M main
git remote add origin https://github.com/Dolkir643/carvector-bot-addon.git
git push -u origin main
```

Если репо уже есть и нужно только отправить изменения:

```bash
cd /Users/kirill/Desktop/addons
git add .
git commit -m "Обновление кода бота"
git push origin main
```

## 2. В Home Assistant (веб-интерфейс)

1. **Настройки** → **Дополнения** → **Магазин дополнений**.
2. Справа вверху нажми **⋮** (три точки) → **Репозитории**.
3. В поле вставь: `https://github.com/Dolkir643/carvector-bot-addon`
4. Нажми **Добавить**, затем **Закрыть**.
5. Подожди несколько секунд или обнови страницу — в списке должно появиться дополнение **CarVector Bot**.

## 3. Установка и настройка

1. Найди **CarVector Bot** в списке дополнений и открой его.
2. Нажми **Установить**, дождись окончания установки.
3. Перейди на вкладку **Конфигурация** и укажи (подставь свои данные):

   - **bot_token** — токен от @BotFather (тот, с которым бот работает на ноуте).
   - **carvector_login** — `paseca@my.com`
   - **carvector_password** — пароль от carvector.ru
   - **manager_chat_id** — `232066339`

4. Нажми **Сохранить**.

## 4. Запуск

1. Вкладка **Информация** (Info).
2. Включи **Запускать при загрузке** (Start on boot), если нужно, чтобы бот стартовал после перезагрузки NUC.
3. Нажми **Запустить** (Start).
4. Открой вкладку **Лог** — должны появиться строки:
   - `Токен OK, бот: @ZapL405_Bot`
   - `Run polling for bot @ZapL405_Bot`

## 5. Проверка

В Telegram напиши боту **/start** и отправь артикул (например **LR174897**). Ответ должен прийти с NUC.

---

**Важно:** На время работы бота на NUC не запускай тот же бот (с тем же токеном) на ноутбуке или на Railway — иначе Telegram будет слать обновления только одному экземпляру.
