import os
from time import sleep

import pytest
import pytest_check as check
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import Select, WebDriverWait

# Адреса сайту. Для Render змініть на https://ваш-сайт.onrender.com/
APP_URL = "http://127.0.0.1:8000/"

# Логін і пароль адміністратора беруться зі змінних середовища,
# щоб пароль не зберігався в коді.
admin_user = {
    "username": os.environ.get("ADMIN_USERNAME", "admin"),
    "password": os.environ.get("ADMIN_PASSWORD", ""),
}
test_client = {
    "full_name": "Тест Клієнт",
    "phone": "+380501234567",
    "email": "test_client@gmail.com",
    "address": "м. Львів, вул. Шевченка, 1",
}


@pytest.fixture
def driver():
    driver = webdriver.Firefox()
    yield driver
    driver.quit()


def login(driver: webdriver.Firefox, user: dict[str, str]) -> None:
    driver.get(url=APP_URL + "login/")

    username_input = driver.find_element(by=By.NAME, value="username")
    username_input.send_keys(user.get("username", ""))
    sleep(0.5)

    password_input = driver.find_element(by=By.NAME, value="password")
    password_input.send_keys(user.get("password", ""))
    sleep(0.5)

    submit_button = driver.find_element(by=By.XPATH, value="//button[.='Увійти']")
    submit_button.click()


def test_admin_login(driver: webdriver.Firefox) -> None:
    """TC_001: вхід адміністратора."""
    login(driver, admin_user)
    sleep(1)

    page_text = driver.find_element(by=By.TAG_NAME, value="body").text
    check.is_true("/login/" not in driver.current_url)
    check.is_in("Огляд системи", page_text)


def test_place_order(driver: webdriver.Firefox) -> None:
    """TC_003: оформлення замовлення клієнтом."""
    driver.get(url=APP_URL + "shop/")

    order_button = driver.find_element(
        by=By.XPATH, value="(//button[contains(., 'Замовити')])[1]"
    )
    order_button.click()
    sleep(1)

    # Форма замовлення: шукаємо її за полем телефону
    form = driver.find_element(by=By.XPATH, value="//form[.//input[@name='phone']]")

    # Спосіб доставки: вибираємо перший справжній варіант зі списку
    for select_element in form.find_elements(by=By.TAG_NAME, value="select"):
        select = Select(select_element)
        select.select_by_index(1 if len(select.options) > 1 else 0)
        sleep(0.5)

    # Текстові поля: ПІБ, телефон, пошта (числове поле «Кількість» пропускаємо)
    short_fields = [
        element
        for element in form.find_elements(
            by=By.CSS_SELECTOR,
            value=(
                "input:not([type='hidden']):not([type='checkbox']):not([type='radio'])"
                ":not([type='submit']):not([type='number'])"
            ),
        )
        if element.is_displayed()
    ]
    short_values = [
        test_client["full_name"],
        test_client["phone"],
        test_client["email"],
    ]
    for element, value in zip(short_fields, short_values):
        element.send_keys(value)
        sleep(0.5)

    # Адреса доставки - велике текстове поле (textarea)
    address_field = form.find_element(by=By.TAG_NAME, value="textarea")
    address_field.send_keys(test_client["address"])
    sleep(0.5)

    submit_button = form.find_element(by=By.CSS_SELECTOR, value="button[type='submit']")
    submit_button.click()

    # Чекаємо до 10 секунд, поки з'явиться сторінка підтвердження
    try:
        WebDriverWait(driver, 10).until(
            lambda d: "дякуємо"
            in d.find_element(by=By.TAG_NAME, value="body").text.lower()
        )
    except TimeoutException:
        pass

    page_text = driver.find_element(by=By.TAG_NAME, value="body").text
    check.is_in(
        "дякуємо",
        page_text.lower(),
        f"Сторінка підтвердження не відкрилась. Текст сторінки: {page_text[:300]}",
    )