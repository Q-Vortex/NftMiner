import json
import time
import os
import argparse
import glob
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.firefox.service import Service
from selenium.common.exceptions import TimeoutException
# ---------- Настройки ----------
ACCOUNTS_DIR = "private/data/accounts"   # директория для хранения аккаунтов
WEB_TELEGRAM_URL = "https://web.telegram.org/a/"
TARGET_CHAT_URL_TEMPLATE = "https://web.telegram.org/k/#{}"
BOT_USERNAME = "@virus_play_bot"
WAIT_TIMEOUT = 60
MAX_WAIT_FOR_LOGIN = 300
POLL_INTERVAL = 1
# --------------------------------

def ensure_directories():
    """Создает необходимые директории если они не существуют"""
    os.makedirs(ACCOUNTS_DIR, exist_ok=True)
    os.makedirs("private/data", exist_ok=True)

def get_account_filename(account_name=None):
    """Генерирует имя файла для аккаунта"""
    if account_name:
        return f"{ACCOUNTS_DIR}/{account_name}.json"
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{ACCOUNTS_DIR}/account_{timestamp}.json"

def list_accounts():
    """Возвращает список всех сохраненных аккаунтов"""
    pattern = os.path.join(ACCOUNTS_DIR, "*.json")
    return sorted(glob.glob(pattern))  # Сортируем для последовательности

def read_localstorage_from_browser(driver):
    """Возвращает объект localStorage как dict"""
    js = "return JSON.stringify(Object.fromEntries(Object.entries(window.localStorage)));"
    res = driver.execute_script(js)
    if res is None:
        return {}
    try:
        return json.loads(res)
    except Exception:
        return {}

def write_localstorage_to_browser(driver, data: dict):
    """Записывает пары ключ/значение в localStorage"""
    payload = json.dumps(data, ensure_ascii=False)
    js = f"""
    (function(){{
        const obj = JSON.parse({json.dumps(payload)});
        for (const k of Object.keys(obj)) {{
            localStorage.setItem(k, String(obj[k]));
        }}
        return true;
    }})();
    """
    return driver.execute_script(js)

def save_localstorage_to_file(driver, path):
    """Сохраняет localStorage в файл"""
    data = read_localstorage_from_browser(driver)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[+] LocalStorage сохранен в {path}")
    return data

def has_auth_keys(localdata: dict) -> bool:
    """Проверка, есть ли в localStorage признаки авторизации Telegram"""
    if not localdata:
        return False
    keys = localdata.keys()
    indicators = ["user_auth", "dc1_auth_key", "dc2_auth_key", "dc3_auth_key", "dc4_auth_key", "dc5_auth_key",
                  "stel_web_auth", "auth_key", "session_id", "kz_version"]
    for ind in indicators:
        if ind in keys:
            return True
    for k in keys:
        if "auth" in k.lower() or k.lower().startswith("dc"):
            return True
    return False

def wait_for_user_login_collect_localstorage(driver, account_file, timeout=MAX_WAIT_FOR_LOGIN):
    """Ожидает появления признаков авторизации и сохраняет аккаунт"""
    start = time.time()
    last_len = -1
    
    print(f"[*] Ожидание авторизации... (максимум {timeout} секунд)")
    print("[*] Пожалуйста, войдите в свой аккаунт Telegram в открывшемся браузере")
    
    while time.time() - start < timeout:
        data = read_localstorage_from_browser(driver)
        if len(data) != last_len:
            last_len = len(data)
            print(f"[*] Обновление localStorage: {len(data)} записей")
            
        if has_auth_keys(data):
            save_localstorage_to_file(driver, account_file)
            print(f"[+] Аккаунт успешно сохранен: {account_file}")
            return True
            
        time.sleep(POLL_INTERVAL)
        
    print("[-] Не удалось обнаружить признаки авторизации в течение отведенного времени")
    return False

def click_button(driver, wait, selector):
    """Нажимает кнопку с обработкой перекрывающих элементов"""
    try:
        element = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
        
        # Пытаемся нажать через JavaScript если обычный клик не работает
        try:
            element.click()
            return True
        except Exception as e:
            print(f"[DEBUG] Обычный клик не сработал, пробуем JavaScript: {e}")
            driver.execute_script("arguments[0].click();", element)
            return True
            
    except Exception as e:
        print(f"[-] Не удалось найти или нажать кнопку {selector}: {e}")
        return False
def register_new_account(account_name=None):
    """Регистрирует новый аккаунт"""
    account_file = get_account_filename(account_name)
    
    if os.path.exists(account_file):
        response = input(f"Аккаунт {account_file} уже существует. Перезаписать? (y/n): ")
        if response.lower() != 'y':
            print("[-] Регистрация отменена")
            return False
    
    options = webdriver.FirefoxOptions()
    options.add_argument("--new-window")
    driver = webdriver.Firefox(options=options)
    
    try:
        print(f"[*] Начата регистрация нового аккаунта: {account_file}")
        driver.get(WEB_TELEGRAM_URL)
        
        success = wait_for_user_login_collect_localstorage(driver, account_file)
        if success:
            print("[+] Регистрация завершена успешно!")
            return True
        else:
            print("[-] Регистрация не удалась")
            return False
            
    finally:
        driver.quit()

def subscribe_to_channel(driver, wait, channel_name):
    """Подписывается на указанный канал"""
    # Проверяем формат имени канала
    if not channel_name.startswith('@'):
        print(f"[-] Ошибка: имя канала должно начинаться с @, получено: {channel_name}")
        return False
    
    # Создаем URL канала
    channel_url = TARGET_CHAT_URL_TEMPLATE.format(channel_name)
    main_window = driver.current_window_handle

    try:
        # Открываем канал в новой вкладке
        driver.execute_script("window.open(arguments[0]);", channel_url)
        driver.switch_to.window(driver.window_handles[-1])
        print(f"[+] Открыли канал {channel_name} в новой вкладке")

        # Подписываемся на канал
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
            subscribe_btn = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "button.btn-primary.btn-color-primary.chat-join.rp"))
            )

            wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-primary.btn-color-primary.chat-join.rp")))
            click_button(driver, wait, "button.btn-primary.btn-color-primary.chat-join.rp")
            print(f"[+] Успешно подписались на канал: {channel_name}")

            time.sleep(1)
            return True
            
        except Exception as e:
            print(f"[-] Ошибка при подписке на канал {channel_name}: {e}")
            return False

    except Exception as e:
        print(f"[-] Ошибка при открытии канала {channel_name}: {e}")
        return False
    
    finally:
        # Всегда закрываем вкладку и возвращаемся к основному окну
        try:
            driver.close()
            driver.switch_to.window(main_window)
            print("[+] Вернулись в основное окно")
        except Exception as e:
            print(f"[-] Ошибка при возврате в основное окно: {e}")

def run_bot_actions(driver, wait, account_file, account_index=None, total_accounts=None):
    """Запускает полную последовательность действий бота для указанного аккаунта в существующей сессии"""
    if not os.path.exists(account_file):
        print(f"[-] Файл аккаунта не найден: {account_file}")
        return False
    
    # Информация о текущем аккаунте
    if account_index is not None and total_accounts is not None:
        account_info = f"[{account_index+1}/{total_accounts}] {os.path.basename(account_file)}"
    else:
        account_info = os.path.basename(account_file)
    
    try:
        print(f"\n{'='*50}")
        print(f"[*] Запуск бота с аккаунтом: {account_info}")
        print(f"{'='*50}")
        
        # Загружаем localStorage
        driver.get(WEB_TELEGRAM_URL)
        time.sleep(1)
        
        with open(account_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        write_localstorage_to_browser(driver, data)
        
        print("[+] LocalStorage загружен. Переходим к боту...")
        target = TARGET_CHAT_URL_TEMPLATE.format(BOT_USERNAME)
        
        # Закрываем все предыдущие вкладки кроме основной
        while len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])
            driver.close()
        driver.switch_to.window(driver.window_handles[0])
        
        # Открываем бота в новой вкладке
        driver.execute_script("window.open(arguments[0], '_blank');", target)
        driver.switch_to.window(driver.window_handles[-1])
        
        # Ожидаем загрузки контента
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
            content = WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.message, div.msg, div.im_dialogs"))
            )
            print("[+] Контент найден")
            
        except Exception as e:
            print("[-] Контент не найден за 3 секунды, перезагружаем страницу...")
            driver.execute_script("location.reload();")
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
                content = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.message, div.msg, div.im_dialogs"))
                )
                print("[+] Контент найден после перезагрузки")
            except Exception as e2:
                print(f"[-] Контент не найден даже после перезагрузки: {e2}")
                return False

        print("[+] Готово — страница открыта с загруженным Local Storage.")

        # Основная последовательность действий с ботом
        try:
            # Нажимаем кнопку команд бота
            click_button(driver, wait, "div.new-message-bot-commands-view")
            print("[+] Кнопка команд нажата")
            
            # Нажимаем кнопку запуска игры
            wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.popup-button.btn.primary.rp")))
            click_button(driver, wait, "button.popup-button.btn.primary.rp")
            print("[+] Кнопка запуска игры нажата")
            
            # Переключаемся в iframe
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "iframe")))
            iframe = driver.find_element(By.CSS_SELECTOR, "iframe")
            driver.switch_to.frame(iframe)
            print("[+] Переключились в iframe")

            # Переходим в рулетку
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href='/roulette']")))
            click_button(driver, wait, "a[href='/roulette']")
            print("[+] Перешли в рулетку")
            
            # Нажимаем на оболочку рулетки
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div._rouletteElementWrapper_1gfbt_101")))
            click_button(driver, wait, "div._rouletteElementWrapper_1gfbt_101")
            print("[+] Нажали на рулетку")
            
            # Нажимаем на спин
            rullete = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "button._spinButton_kqkkw_151")))

            element_text = rullete.text.strip().lower()
            if "раскрутить за" in element_text:
                print("[-] Рулетка отключена, завершаем сессию для этого аккаунта")
                return False
            else:
                click_button(driver, wait, "button._spinButton_kqkkw_151")

            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div._customAlertContent_1wvss_1")))
            element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div._customAlertContent_1wvss_1 a")))
            channel_name = element.text
            print(f"[+] Получен канал: {channel_name}")

            # Используем новую функцию для подписки на канал
            subscription_success = subscribe_to_channel(driver, wait, channel_name)
            
            if not subscription_success:
                print(f"[-] Не удалось подписаться на канал {channel_name}, но продолжаем...")

            # Возвращаемся в iframe
            wait.until(EC.frame_to_be_available_and_switch_to_it((By.CSS_SELECTOR, "iframe")))
            print("[+] Успешно переключились в iframe")

            # Нажимаем OK
            try:
                ok_button_xpath = "//button[text()='OK']"
                wait.until(EC.presence_of_element_located((By.XPATH, ok_button_xpath)))
                wait.until(EC.element_to_be_clickable((By.XPATH, ok_button_xpath)))
                ok_button = driver.find_element(By.XPATH, ok_button_xpath)
                ok_button.click()
                print("[+] Нажата кнопка OK")
                
            except Exception as e:
                print(f"[-] Ошибка при нажатии OK: {e}")

            # Снова нажимаем на спин
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "button._spinButton_kqkkw_151")))
            wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button._spinButton_kqkkw_151")))
            click_button(driver, wait, "button._spinButton_kqkkw_151")
            print("[+] Крутим рулетку второй раз")

            # Ждем появления кнопки claim
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "button._claimButton_18gr7_197")))
            print("[+] Кнопка claim найдена - игра завершена!")
            
            print(f"[+] Действия бота завершены для аккаунта {account_info}")
            
        except Exception as e:
            print(f"[-] Ошибка при выполнении действий бота: {e}")
            return False
        
        return True
        
    except Exception as e:
        print(f"[-] Общая ошибка при работе с аккаунтом: {e}")
        return False
    finally:
        print(f"[*] Завершено для аккаунта {account_info}")

def run_all_accounts():
    """Запускает бота для всех аккаунтов по очереди в одной сессии"""
    accounts = list_accounts()
    if not accounts:
        print("[-] Аккаунты не найдены. Используйте --register для создания нового.")
        return
    
    print(f"[*] Найдено аккаунтов: {len(accounts)}")
    print("[*] Запуск для всех аккаунтов в ОДНОЙ сессии...")
    
    options = webdriver.FirefoxOptions()
    options.add_argument("--new-window")
    start = time.time()
    driver = webdriver.Firefox(options=options)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    print(f"[*] Firefox стартовал за {round(time.time()-start, 2)} сек.")
    
    successful = 0
    failed = 0
    
    try:
        for i, account_file in enumerate(accounts):
            try:
                success = run_bot_actions(driver, wait, account_file, account_index=i, total_accounts=len(accounts))
                if success:
                    successful += 1
                else:
                    failed += 1
                    
            except Exception as e:
                print(f"[-] Критическая ошибка при обработке аккаунта {account_file}: {e}")
                failed += 1
            
            if i < len(accounts) - 1:
                print(f"[*] Пауза 2 секунды перед следующим аккаунтом...")
                time.sleep(2)
    
    except Exception as e:
        print(f"[-] Критическая ошибка в основной сессии: {e}")
        failed = len(accounts) - successful
    
    finally:
        print(f"[*] Завершение работы браузера после всех аккаунтов...")
        start = time.time()
        driver.quit()
        print(f"[*] Firefox завершился за {round(time.time()-start, 2)} сек.")
    
    print(f"\n{'='*50}")
    print(f"[ИТОГ] Успешно: {successful}, Неудачно: {failed}, Всего: {len(accounts)}")
    print(f"{'='*50}")

def main():
    ensure_directories()
    
    parser = argparse.ArgumentParser(description='Telegram Bot Automation')
    parser.add_argument('--register', action='store_true', 
                       help='Зарегистрировать новый аккаунт')
    parser.add_argument('--list', action='store_true',
                       help='Показать список всех аккаунтов')
    parser.add_argument('--all', action='store_true',
                       help='Запустить для всех аккаунтов (по умолчанию)')
    
    args = parser.parse_args()
    
    if args.list:
        accounts = list_accounts()
        if accounts:
            print("[*] Доступные аккаунты:")
            for i, acc in enumerate(accounts):
                print(f"  {i+1}. {os.path.basename(acc)}")
            print(f"\nВсего: {len(accounts)} аккаунтов")
        else:
            print("[-] Аккаунты не найдены")
        return
    
    if args.register:
        register_new_account(args.account)
        return
    
    run_all_accounts()

if __name__ == "__main__":
    main()