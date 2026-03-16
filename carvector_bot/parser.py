"""Парсер CarVector.ru — поиск запчастей LAND ROVER и сбор цен."""
import re
import time
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup


class CarVectorParser:
    """Клиент для авторизации и парсинга цен по артикулам (только LAND ROVER)."""

    BASE_URL = "https://carvector.ru"
    COLOR_MAP = {
        "#2ECC71": ("🟢", "В наличии в Москве"),
        "#FFEB3B": ("🟡", "Надежный поставщик"),
        "#72B2DD": ("🔵", "100% гарантия оригинал"),
        "#1ABC9C": ("🟠", "Невозвратные позиции"),
        "#E77346": ("🟤", "Популярный поставщик"),
    }

    def __init__(self, username: str, password: str, debug_save_html: bool = False):
        self.username = username
        self.password = password
        self.debug_save_html = debug_save_html
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Origin": self.BASE_URL,
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
        })
        self.is_authorized = False

    def authorize(self) -> bool:
        """Вход на сайт. Парсит форму со страницы и отправляет все нужные поля."""
        try:
            main_page = self.session.get(
                f"{self.BASE_URL}/",
                timeout=15,
                headers={"Referer": f"{self.BASE_URL}/"},
            )
            if main_page.status_code != 200:
                return False

            soup = BeautifulSoup(main_page.text, "html.parser")
            login_data = self._get_login_form_data(soup)
            if not login_data:
                # Fallback: типичные имена полей для carvector.ru
                login_data = {"login": self.username, "pass": self.password, "go": "Вход"}

            post_url = f"{self.BASE_URL}/"
            form = soup.find("form", method=re.compile(r"post", re.I))
            if form and form.get("action"):
                action = form["action"].strip()
                post_url = action if action.startswith("http") else f"{self.BASE_URL}/{action.lstrip('/')}"

            def do_post(data: dict) -> requests.Response:
                return self.session.post(
                    post_url,
                    data=data,
                    timeout=15,
                    allow_redirects=True,
                    headers={
                        "Referer": main_page.url or f"{self.BASE_URL}/",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )

            response = do_post(login_data)
            ok = self._check_login_success(response)

            # Если не вышло и использовали fallback — пробуем с полем email вместо login
            if not ok and login_data.get("login") == self.username:
                alt_data = {"email": self.username, "pass": self.password, "go": "Вход"}
                response = do_post(alt_data)
                ok = self._check_login_success(response)

            if self.debug_save_html or not ok:
                try:
                    with open("debug_login_response.html", "w", encoding="utf-8") as f:
                        f.write(response.text or "")
                except Exception:
                    pass
            return ok
        except Exception:
            return False

    def _get_login_form_data(self, soup: BeautifulSoup) -> dict | None:
        """Извлекает из страницы данные формы входа (все input) и подставляет логин/пароль."""
        login_names = ("login", "email", "username", "user", "auth_login", "e-mail")
        for form in soup.find_all("form"):
            inputs = form.find_all("input")
            has_login = any(
                inp.get("name") and inp.get("name", "").lower() in login_names
                for inp in inputs
            )
            if not has_login:
                has_login = any(
                    "login" in (inp.get("name") or "").lower() or inp.get("name") == "email"
                    for inp in inputs
                )
            has_pass = any(
                inp.get("type", "").lower() == "password" and inp.get("name") for inp in inputs
            )
            if not (has_login and has_pass):
                continue
            data = {}
            for inp in inputs:
                name = inp.get("name")
                if not name:
                    continue
                if inp.get("type", "").lower() == "password":
                    data[name] = self.password
                elif name.lower() in login_names or "login" in name.lower() or name == "email":
                    data[name] = self.username
                elif inp.get("value") is not None:
                    data[name] = inp["value"]
                elif inp.get("type", "").lower() in ("submit", "image"):
                    data[name] = inp.get("value") or "Вход"
            if data:
                return data
        return None

    def _check_login_success(self, response: requests.Response) -> bool:
        """Проверяет, что после POST мы залогинены."""
        if response.status_code != 200:
            return False
        text = response.text or ""
        # Признаки успешного входа (проверяем первыми)
        if "Выход" in text or "выйти" in text.lower():
            self.is_authorized = True
            return True
        if self.username and (self.username.split("@")[0] in text or self.username in text):
            self.is_authorized = True
            return True
        if "Личный кабинет" in text or "личный кабинет" in text.lower():
            self.is_authorized = True
            return True
        if "Заказы" in text and "Договор" in text:
            self.is_authorized = True
            return True
        # Признаки неуспеха: снова форма входа
        if 'name="login"' in text and ('name="pass"' in text or 'type="password"' in text):
            return False
        return False

    @staticmethod
    def parse_price(price_text: str) -> float | None:
        """Извлекает число из строки с ценой."""
        cleaned = price_text.replace("\xa0", " ").replace("&nbsp;", " ")
        match = re.search(r"([\d\s,.]+)", cleaned)
        if match:
            clean = match.group(1).replace(" ", "").replace(",", ".")
            try:
                return float(clean)
            except ValueError:
                return None
        return None

    @staticmethod
    def _style_to_hex(style: str) -> str | None:
        """Извлекает цвет фона из style: поддерживает #hex и rgb(r,g,b). Возвращает hex в верхнем регистре."""
        if not style:
            return None
        # background-color: #72B2DD или background: #72B2DD
        for pattern in (r"background-color:\s*#([A-Fa-f0-9]{6})\b", r"background:\s*#([A-Fa-f0-9]{6})\b"):
            hex_match = re.search(pattern, style)
            if hex_match:
                return "#" + hex_match.group(1).upper()
        for pattern in (r"background-color:\s*rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", r"background:\s*rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)"):
            rgb_match = re.search(pattern, style)
            if rgb_match:
                r, g, b = (int(x) for x in rgb_match.groups())
                return f"#{r:02X}{g:02X}{b:02X}"
        return None

    def get_color_info(self, bg_color: str | None) -> tuple[str, str]:
        if bg_color:
            key = bg_color.upper().strip()
            if key in self.COLOR_MAP:
                return self.COLOR_MAP[key]
        return ("⚪", "Обычный поставщик")

    @staticmethod
    def _add_sort_to_url(url: str) -> str:
        """Добавляет сортировку по цене к URL страницы с ценами."""
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        query.update({"selectLinkName": ["price"], "selectSortDirection": ["0"]})
        return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

    def _get_code_from_search_href(self, href: str) -> str | None:
        """Извлекает код артикула из href вида /search/Brand/Code."""
        if not href:
            return None
        path = (href.split("?")[0] or "").strip("/")
        if path.startswith("search/"):
            path = path[7:]
        parts = path.split("/")
        if len(parts) >= 2:
            return re.sub(r"[\s\-]", "", (parts[-1] or "").upper())
        return None

    def _find_land_rover_in_soup(self, soup: BeautifulSoup, part_number: str) -> str | None:
        """Возвращает ссылку только при точном совпадении артикула в таблице globalCase (не первую попавшуюся, не DYC500040)."""
        clean_requested = re.sub(r"[\s\-]", "", part_number).upper()
        table = soup.find("table", class_=re.compile(r"globalCase"))
        if table:
            for row in table.find_all("tr"):
                brand_cell = row.find("td", class_=re.compile(r"caseBrand|resultBrand"))
                if not brand_cell or "LAND ROVER" not in brand_cell.get_text(strip=True):
                    continue
                link = row.find("a", class_=re.compile(r"startSearching"), href=re.compile(r"^/search/"))
                if not link:
                    continue
                href = link.get("href", "")
                row_code = self._get_code_from_search_href(href)
                if row_code and row_code == clean_requested:
                    return f"{self.BASE_URL}{href}" if href.startswith("/") else href
        return None

    def _find_direct_part_link(self, soup: BeautifulSoup, part_number: str) -> str | None:
        """Ищет на странице ссылку вида /search/.../PART_NUMBER (прямая ссылка на запрошенный артикул)."""
        clean = re.sub(r"[\s\-]", "", part_number).upper()
        for a in soup.find_all("a", href=re.compile(r"/search/", re.I)):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            code = self._get_code_from_search_href(href)
            if code and code == clean:
                base = self.BASE_URL.rstrip("/")
                path = href if href.startswith("http") else f"{base}{href}" if href.startswith("/") else f"{base}/{href}"
                return path.split("?")[0]
        return None

    def get_land_rover_url(self, part_number: str) -> str | None:
        """Основной URL: поиск по артикулу с FranchiseeId (полная таблица для LR142260 и др.)."""
        part_clean = part_number.strip()
        search_url = f"{self.BASE_URL}/search/?pcode={part_clean}&FranchiseeId=156811934"
        return self._add_sort_to_url(search_url)

    def get_land_rover_url_candidates(self, part_number: str) -> list[str]:
        """
        Несколько URL для поиска по артикулу. Если по первому таблица пустая или страница другая —
        пробуем без FranchiseeId и канонический /search/LAND ROVER/PART.
        """
        part_clean = part_number.strip()
        part_upper = part_clean.upper()
        return [
            self._add_sort_to_url(f"{self.BASE_URL}/search/?pcode={part_clean}&FranchiseeId=156811934"),
            self._add_sort_to_url(f"{self.BASE_URL}/search?pcode={part_clean}"),
            self._add_sort_to_url(f"{self.BASE_URL}/search/LAND%20ROVER/{part_upper}"),
        ]

    def search_land_rover(self, part_number: str) -> dict | None:
        """
        Поиск только LAND ROVER. Пробуем по очереди несколько URL (с FranchiseeId, без, канонический),
        пока один не вернёт непустой список предложений из searchResultsTable.
        """
        if not self.is_authorized:
            return None
        all_offers = None
        for url in self.get_land_rover_url_candidates(part_number):
            all_offers = self.parse_all_prices_simple(url, part_number)
            if all_offers:
                break
        if not all_offers:
            return None

        def _select_diverse(offers: list[dict], limit: int) -> list[dict]:
            """Выбирает до limit предложений: сначала по одному самому дешёвому каждого цвета/статуса,
            затем добивает до лимита просто самыми дешёвыми."""
            if not offers:
                return []
            by_price = lambda o: o.get("price") or 0
            # Порядок: по одному самому дешёвому каждого цвета (🔵🟡🟢🟠🟤), затем добиваем по цене
            priority_statuses = [
                "100% гарантия оригинал",      # 🔵
                "Надежный поставщик",          # 🟡
                "В наличии в Москве",          # 🟢
                "Невозвратные позиции",        # 🟠
                "Популярный поставщик",        # 🟤
            ]
            selected: list[dict] = []
            used_indices: set[int] = set()
            for status in priority_statuses:
                cand = [(i, o) for i, o in enumerate(offers) if o.get("status") == status]
                if not cand:
                    continue
                best_idx, best = min(cand, key=lambda x: by_price(x[1]))
                selected.append(best)
                used_indices.add(best_idx)
                if len(selected) >= limit:
                    return selected
            # добираем просто самыми дешёвыми из оставшихся
            remaining = [o for i, o in enumerate(offers) if i not in used_indices]
            remaining_sorted = sorted(remaining, key=by_price)
            for o in remaining_sorted:
                if len(selected) >= limit:
                    break
                selected.append(o)
            return selected

        requested_all = [o for o in all_offers if o.get("type") == "Запрашиваемый"]
        originals_all = [o for o in all_offers if o.get("type") == "Оригинальная замена"]
        requested = _select_diverse(requested_all, 5)
        originals = _select_diverse(originals_all, 5)
        # В каждой группе — от меньшей цены к большей (сначала самые выгодные)
        requested.sort(key=lambda o: o.get("price") or 0)
        originals.sort(key=lambda o: o.get("price") or 0)
        positions = []
        for i, offer in enumerate(requested, 1):
            positions.append({
                "position_num": i,
                "type": "Запрашиваемый",
                "brand": "LAND ROVER",
                "code": offer.get("code", part_number),
                "description": offer.get("description", ""),
                "offers": [offer],
            })
        for i, offer in enumerate(originals, 6):
            positions.append({
                "position_num": i,
                "type": "Оригинальная замена",
                "brand": "LAND ROVER",
                "code": offer.get("code", part_number),
                "description": offer.get("description", ""),
                "offers": [offer],
            })
        if not positions:
            return None
        all_prices = [p for pos in positions for p in (pos.get("offers") or []) if p.get("price")]
        min_price = min(p["price"] for p in all_prices) if all_prices else None
        return {
            "part_number": part_number,
            "positions": positions,
            "total_requested": len(requested),
            "total_originals": len(originals),
            "min_price": min_price,
        }

    def _parse_search_page_items(self, part_number: str) -> list[dict]:
        """Парсит страницу поиска: все позиции (бренд, код, описание, url). Классифицирует запрашиваемый/замена."""
        clean_part = re.sub(r"[\s\-]", "", part_number).upper()
        url = f"{self.BASE_URL}/search?pcode={part_number}"
        try:
            response = self.session.get(url, timeout=15)
            if response.status_code != 200:
                return []
            if self.debug_save_html:
                with open(f"debug_поиск_{part_number}.html", "w", encoding="utf-8") as f:
                    f.write(response.text)
            soup = BeautifulSoup(response.text, "html.parser")
            items = []
            # На сайте: таблица globalCase, строки с классом startSearching, ячейки caseBrand / casePartCode / caseDescription (с пробелами в классе)
            table = soup.find("table", class_=re.compile(r"globalCase"))
            if not table:
                table = soup
            for row in table.find_all("tr"):
                link = row.find("a", class_=re.compile(r"startSearching"), href=re.compile(r"^/search/"))
                if not link:
                    continue
                href = link.get("href", "")
                full_url = f"{self.BASE_URL}{href}" if href.startswith("/") else href
                # Бренд и код из data-link на tr или из href: /search/Brand/Code
                url_brand = url_code = None
                data_link = row.get("data-link") or href
                if data_link:
                    path = (data_link.split("?")[0] or "").strip("/")
                    if path.startswith("search/"):
                        path = path[7:]
                    parts_path = path.split("/")
                    if len(parts_path) >= 2:
                        url_brand = parts_path[0].replace("%20", " ")
                        url_code = parts_path[1]
                brand_cell = row.find("td", class_=re.compile(r"caseBrand|resultBrand"))
                brand = brand_cell.get_text(strip=True) if brand_cell else ""
                if not brand and url_brand:
                    brand = url_brand.replace("%20", " ")
                if not brand:
                    brand = "Неизвестно"
                code_cell = row.find("td", class_=re.compile(r"casePartCode|resultPartCode"))
                code = code_cell.get_text(strip=True) if code_cell else (url_code or part_number)
                if not code or code == part_number:
                    if url_code:
                        code = url_code
                    else:
                        code = part_number
                desc_cell = row.find("td", class_=re.compile(r"caseDescription|resultDescription"))
                description = desc_cell.get_text(strip=True) if desc_cell else ""
                clean_code = re.sub(r"[\s\-]", "", str(code)).upper()
                offer_type = "Запрашиваемый" if clean_code == clean_part else "Оригинальная замена"
                items.append({
                    "brand": brand,
                    "code": code,
                    "description": description,
                    "url": full_url,
                    "type": offer_type,
                })
            return items
        except Exception:
            return []

    def _parse_price_page(self, url: str, brand: str, code: str) -> list[dict]:
        """Парсит одну страницу с ценами (одна позиция), возвращает список предложений."""
        try:
            response = self.session.get(url, timeout=15)
            if response.status_code != 200:
                return []
            soup = BeautifulSoup(response.text, "html.parser")
            table = soup.find("table", id="searchResultsTable")
            if not table:
                return []
            offers = []
            for row in table.find_all("tr"):
                price_cell = row.find("td", class_=re.compile(r"resultPrice"))
                if not price_cell:
                    continue
                style = row.get("style", "")
                bg_color = self._style_to_hex(style)
                emoji, status = self.get_color_info(bg_color)
                price_text = price_cell.get_text(strip=True)
                price_value = self.parse_price(price_text)
                if not price_value:
                    continue
                code_cell = row.find("td", class_=re.compile(r"resultPartCode|resultBrandNumber"))
                row_code = code_cell.get_text(strip=True) if code_cell else code
                desc_cell = row.find("td", class_=re.compile(r"resultDescription"))
                star = row.find("span", class_=re.compile(r"fr-icon-star3"))
                offers.append({
                    "emoji": emoji,
                    "status": status,
                    "brand": brand,
                    "code": row_code,
                    "description": (desc_cell.get_text(strip=True) if desc_cell else ""),
                    "stock": "",
                    "deadline": "",
                    "update_time": "",
                    "price": price_value,
                    "price_text": price_text,
                    "is_reliable": bool(star),
                    "type": "Запрашиваемый",
                })
            return offers
        except Exception:
            return []

    def search_all(self, part_number: str) -> dict | None:
        """
        Поиск по всем брендам. Возвращает до 5 позиций «Запрашиваемый артикул» (номера 1–5)
        и до 5 позиций «Оригинальные замены» (номера 6–10). Нумерация сохраняется для заказа.
        """
        if not self.is_authorized:
            return None
        items = self._parse_search_page_items(part_number)
        if not items:
            return None
        requested = [i for i in items if i["type"] == "Запрашиваемый"][:5]
        originals = [i for i in items if i["type"] == "Оригинальная замена"][:5]
        positions = []
        position_num = 1
        for item in requested:
            url_sorted = self._add_sort_to_url(item["url"])
            offers = self._parse_price_page(url_sorted, item["brand"], item["code"])
            if offers:
                offers.sort(key=lambda x: x["price"])
            positions.append({
                "position_num": position_num,
                "type": "Запрашиваемый",
                "brand": item["brand"],
                "code": item["code"],
                "description": item["description"],
                "offers": offers,
            })
            position_num += 1
            time.sleep(0.5)
        for item in originals:
            url_sorted = self._add_sort_to_url(item["url"])
            offers = self._parse_price_page(url_sorted, item["brand"], item["code"])
            if offers:
                offers.sort(key=lambda x: x["price"])
            positions.append({
                "position_num": position_num,
                "type": "Оригинальная замена",
                "brand": item["brand"],
                "code": item["code"],
                "description": item["description"],
                "offers": offers,
            })
            position_num += 1
            time.sleep(0.5)
        if not positions:
            return None
        all_prices = [p for pos in positions for p in (pos.get("offers") or []) if p.get("price")]
        min_price = min(p["price"] for p in all_prices) if all_prices else None
        return {
            "part_number": part_number,
            "positions": positions,
            "total_requested": len(requested),
            "total_originals": len(originals),
            "min_price": min_price,
        }

    def parse_all_prices_simple(self, url: str, part_number: str) -> list[dict] | None:
        """Парсит страницу с ценами и возвращает список предложений."""
        clean_part = re.sub(r"[\s\-]", "", part_number).upper()
        try:
            response = self.session.get(url, timeout=15)
            if response.status_code != 200:
                return None
            if self.debug_save_html:
                with open(f"debug_цены_{part_number}.html", "w", encoding="utf-8") as f:
                    f.write(response.text)
            soup = BeautifulSoup(response.text, "html.parser")
            table = soup.find("table", id="searchResultsTable")
            if not table:
                return None
            offers = []
            for row in table.find_all("tr"):
                price_cell = row.find("td", class_=re.compile(r"resultPrice"))
                if not price_cell:
                    continue
                style = row.get("style", "")
                bg_color = self._style_to_hex(style)
                emoji, status = self.get_color_info(bg_color)
                price_text = price_cell.get_text(strip=True)
                price_value = self.parse_price(price_text)
                if not price_value:
                    continue
                code_cell = row.find("td", class_=re.compile(r"resultPartCode|resultBrandNumber"))
                code = code_cell.get_text(strip=True) if code_cell else part_number
                clean_code = re.sub(r"[\s\-]", "", code).upper()
                offer_type = "Запрашиваемый" if clean_code == clean_part else "Оригинальная замена"
                desc_cell = row.find("td", class_=re.compile(r"resultDescription"))
                stock_cell = row.find("td", class_=re.compile(r"resultAvailability"))
                deadline_cell = row.find("td", class_=re.compile(r"resultDeadline"))
                update_cell = row.find("td", class_=re.compile(r"resultUpdateTime"))
                star = row.find("span", class_=re.compile(r"fr-icon-star3"))
                offers.append({
                    "emoji": emoji,
                    "status": status,
                    "brand": "LAND ROVER",
                    "code": code,
                    "description": (desc_cell.get_text(strip=True) if desc_cell else ""),
                    "stock": stock_cell.get_text(strip=True) if stock_cell else "0",
                    "deadline": deadline_cell.get_text(strip=True) if deadline_cell else "",
                    "update_time": update_cell.get_text(strip=True) if update_cell else "",
                    "price": price_value,
                    "price_text": price_text,
                    "is_reliable": bool(star),
                    "type": offer_type,
                })
            return offers
        except Exception:
            return None

