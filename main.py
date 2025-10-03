import json
import time
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.firefox import GeckoDriverManager

# ---------- Настройки ----------
LOCALSTORAGE_JSON_PATH = "localstorage.json"   # где хранится/будет сохранён localStorage
WEB_TELEGRAM_URL = "https://web.telegram.org/a/"  # стартовая страница (можно менять)
TARGET_CHAT_URL_TEMPLATE = "https://web.telegram.org/k/#@{}"  # если нужно открыть бота после
BOT_USERNAME = "virus_play_bot"
WAIT_TIMEOUT = 60  # seconds (ожидание загрузки DOM элементов при нормальной работе)
MAX_WAIT_FOR_LOGIN = 300  # seconds — максимум ждать пока пользователь зарегистрируется/войдёт
POLL_INTERVAL = 1  # как часто опрашивать localStorage при ожидании (сек)
# --------------------------------

def read_localstorage_from_browser(driver):
    """Возвращает объект localStorage как dict (сериализованный в JS и возвращённый в Python)."""
    js = "return JSON.stringify(Object.fromEntries(Object.entries(window.localStorage)));"
    res = driver.execute_script(js)
    if res is None:
        return {}
    try:
        return json.loads(res)
    except Exception:
        return {}

def write_localstorage_to_browser(driver, data: dict):
    """Записывает пары ключ/значение в localStorage.
       Используем JSON.stringify в JS, чтобы корректно экранировать строки."""
    # Преобразуем dict в JSON-строку и в JS распакуем её
    payload = json.dumps(data, ensure_ascii=False)
    js = f"""
    (function(){{
        const obj = JSON.parse({json.dumps(payload)});
        for (const k of Object.keys(obj)) {{
            // приводим всё к строкам (localStorage хранит только строки)
            localStorage.setItem(k, String(obj[k]));
        }}
        return true;
    }})();
    """
    return driver.execute_script(js)

def save_localstorage_to_file(driver, path):
    data = read_localstorage_from_browser(driver)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data

def has_auth_keys(localdata: dict) -> bool:
    """Проверка, есть ли в localStorage признаки авторизации Telegram.
       Перечислим ряд часто встречающихся ключей; также сработает если есть любой ключ с 'auth' или 'dc'."""
    if not localdata:
        return False
    # Ядро признаков
    keys = localdata.keys()
    indicators = ["user_auth", "dc1_auth_key", "dc2_auth_key", "dc3_auth_key", "dc4_auth_key", "dc5_auth_key",
                  "stel_web_auth", "auth_key", "session_id", "kz_version"]
    for ind in indicators:
        if ind in keys:
            return True
    # fallback: есть ли ключи с 'auth' или начинающиеся с 'dc'
    for k in keys:
        if "auth" in k.lower() or k.lower().startswith("dc"):
            return True
    return False

def wait_for_user_login_collect_localstorage(driver, timeout=MAX_WAIT_FOR_LOGIN):
    """Ожидает появления признаков авторизации в localStorage и сохраняет файл.
       Возвращает dict localStorage или None, если не найдено за timeout."""
    start = time.time()
    last_len = -1
    while time.time() - start < timeout:
        data = read_localstorage_from_browser(driver)
        # удобный прогресс — если localStorage вырос — обновляем таймер (чтобы не выйти при долгом наборе)
        if len(data) != last_len:
            last_len = len(data)
        if has_auth_keys(data):
            # нашли признаки авторизации — сохраняем и возвращаем
            save_localstorage_to_file(driver, LOCALSTORAGE_JSON_PATH)
            print(f"[+] Найдены ключи авторизации, localStorage сохранён в {LOCALSTORAGE_JSON_PATH}")
            return data
        time.sleep(POLL_INTERVAL)
    print("[-] Не удалось обнаружить признаки авторизации в localStorage за отведённое время.")
    return None

def click_webapp_button(driver, wait):
    """Находит и нажимает на кнопку WebApp с указанным классом."""
    try:
        # Ждем появления кнопки и кликаем по ней
        button_selector = "div.new-message-bot-commands-view"
        button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, button_selector)))
        button.click()
        print("[+] Кнопка 'START THE GAME' успешно нажата.")
        return True
    except Exception as e:
        print(f"[-] Не удалось найти или нажать кнопку: {e}")
        return False

def main():
    options = webdriver.FirefoxOptions()
    options.add_argument("--new-window")
    # можно убрать headless, чтобы всё показывалось (по умолчанию окно видно)
    # options.headless = True

    driver = webdriver.Firefox(service=FirefoxService(GeckoDriverManager().install()), options=options)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    try:
        if os.path.exists(LOCALSTORAGE_JSON_PATH):
            # Если файл есть — читаем и пишем его в localStorage перед загрузкой целевой страницы
            print("[*] Найден localstorage.json — загружаю в браузер.")
            driver.get("https://web.telegram.org")  # сначала открыть тот же домен, чтобы иметь доступ к localStorage
            time.sleep(1)  # даём немного piydi инициализироваться
            with open(LOCALSTORAGE_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            write_localstorage_to_browser(driver, data)
            print("[+] LocalStorage загружен в браузер. Перехожу на основной URL.")
            driver.get(WEB_TELEGRAM_URL)
            # далее можно открыть целевой чат/бота
            target = TARGET_CHAT_URL_TEMPLATE.format(BOT_USERNAME)
            driver.execute_script("window.open(arguments[0], '_blank');", target)
            driver.switch_to.window(driver.window_handles[-1])
            # ждём загрузки сообщений/интерфейса (грубая попытка)
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.message, div.msg, div.im_dialogs")))
            except Exception:
                time.sleep(2)
            print("[+] Готово — страница открыта с загруженным localStorage.")
            target = TARGET_CHAT_URL_TEMPLATE.format(BOT_USERNAME)
            driver.execute_script("window.open(arguments[0], '_blank');", target)
            driver.switch_to.window(driver.window_handles[-1])
            
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.message, div.msg, div.im_dialogs")))
            click_webapp_button(driver, wait)
            
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "button.popup-button.btn.primary.rp")))
            click_webapp_button(driver, wait)
            return

        # Если файла нет — открываем страницу и ждём, пока пользователь залогинится вручную
        print("[*] localstorage.json не найден. Открываю Web Telegram — дождись регистрации/входа в течение", MAX_WAIT_FOR_LOGIN, "сек.")
        driver.get(WEB_TELEGRAM_URL)
        time.sleep(1)
        # Возможны разные варианты: пользователь сначала кликает Login -> вводит код, либо сканит QR и т.д.
        # Мы будем опрашивать localStorage и ждать появления признаков авторизации.
        found = wait_for_user_login_collect_localstorage(driver, timeout=MAX_WAIT_FOR_LOGIN)
        if found:
            # после сохранения можно продолжить (например, открыть бота)
            target = TARGET_CHAT_URL_TEMPLATE.format(BOT_USERNAME)
            driver.execute_script("window.open(arguments[0], '_blank');", target)
            driver.switch_to.window(driver.window_handles[-1])
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.message, div.msg, div.im_dialogs")))
            except Exception:
                time.sleep(2)
            print("[+] Открыт целевой чат/бот.")
        else:
            print("[-] Пользователь не выполнил вход в отведённое время. Скрипт завершает работу.")
    finally:
        # оставляем окно открытым для ручных действий — не закрываем драйвер
        print("[*] Скрипт завершён. Браузер остаётся открытым для ручных действий.")

if __name__ == "__main__":
    main()
