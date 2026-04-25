"""
pharmeasy_scraper.py — Parallel Selenium scraper for PharmEasy
Launches one headless Chrome per medicine simultaneously.
Returns top 3 product page links + product image per medicine.

Works on:
  - Windows (local dev)
  - GCP Linux VM (headless)

Requirements:
  pip install selenium webdriver-manager
"""

import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ── Chrome setup ──────────────────────────────────────────────────────────────

def _make_driver() -> webdriver.Chrome:
    """Create a headless Chrome instance. Works on Windows + Linux/GCP."""
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    # Try webdriver-manager first, fall back to system chromedriver
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        import os
        driver_path = ChromeDriverManager().install()
        try:
            os.chmod(driver_path, 0o755)
        except Exception:
            pass
        service = Service(driver_path)
    except Exception:
        service = Service()  # uses system chromedriver (GCP)

    driver = webdriver.Chrome(service=service, options=opts)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


# ── Image alt text extraction ─────────────────────────────────────────────────

def _alt_from_title(title: str) -> str:
    """
    PharmEasy image alt text == product name only (everything before ' By ').

    e.g. "Omee 20mg Strip Of 20 Capsules By ALKEM LABORATORIES LTD 20 Capsule(s)..."
      →  "Omee 20mg Strip Of 20 Capsules"
    """
    # Split on " By " (case-insensitive) and take the first part
    parts = re.split(r'\s+[Bb]y\s+', title, maxsplit=1)
    return parts[0].strip()


# ── Fetch image from the product page (fallback) ──────────────────────────────

def _fetch_image_from_product_page(driver: webdriver.Chrome, product_url: str, alt_text: str) -> str | None:
    """
    Navigate to the product page and grab the src of the main product image.
    Uses the alt text we derived from the title for a precise match.
    Falls back to any pharmeasy CDN image if alt match fails.
    Returns the image URL string or None.
    """
    try:
        driver.get(product_url)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "img"))
        )

        # Try exact alt match first
        imgs = driver.find_elements(By.CSS_SELECTOR, f'img[alt="{alt_text}"]')
        for img in imgs:
            src = img.get_attribute("src") or ""
            if "cdn" in src and src.startswith("https://"):
                return src

        # Fallback — any image from PharmEasy's CDN on this page
        all_imgs = driver.find_elements(By.TAG_NAME, "img")
        for img in all_imgs:
            src = img.get_attribute("src") or ""
            if "cdn01.pharmeasy.in" in src or "cdn02.pharmeasy.in" in src:
                if src.startswith("https://"):
                    return src

    except Exception:
        pass

    return None


# ── Single medicine search ────────────────────────────────────────────────────

def search_one(medicine_name: str, dosage: str = "", top_n: int = 3) -> dict:
    """
    Search PharmEasy for one medicine.
    Returns:
      {
        "medicine": "Metformin",
        "links": [
          {
            "title": "Metformin 500mg Tab...",
            "url":   "https://pharmeasy.in/...",
            "image": "https://cdn01.pharmeasy.in/..."   ← NEW (None if not found)
          },
          ...
        ],
        "error": None
      }
    """
    query = f"{medicine_name} {dosage}".strip()
    url   = f"https://pharmeasy.in/search/all?name={query.replace(' ', '%20')}"

    driver = None
    try:
        driver = _make_driver()
        driver.get(url)

        wait = WebDriverWait(driver, 15)

        RESULT_CONTAINER_SELECTORS = [
            "div.search-listing-page",
            "div[class*='search-listing']",
            "div[class*='product-list']",
            "div[class*='ProductList']",
            "main",
        ]

        try:
            wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "a[href*='online-medicine-order']")
                )
            )
        except Exception:
            time.sleep(3)

        container = None
        for selector in RESULT_CONTAINER_SELECTORS:
            els = driver.find_elements(By.CSS_SELECTOR, selector)
            if els:
                container = els[0]
                break

        scope   = container if container else driver
        anchors = scope.find_elements(
            By.CSS_SELECTOR, "a[href*='online-medicine-order']"
        )

        seen_urls    = set()
        candidates   = []   # collect (title, href, anchor_element) first

        for anchor in anchors:
            href  = anchor.get_attribute("href") or ""
            title = anchor.get_attribute("title") or anchor.text.strip()
            title = re.sub(r"\s+", " ", title).strip()

            if not href or href in seen_urls:
                continue
            if not re.search(r'/online-medicine-order/[a-z0-9-]+-\d+$', href):
                continue
            if not title:
                title = medicine_name

            seen_urls.add(href)
            candidates.append((title, href, anchor))

            if len(candidates) >= top_n:
                break

        results = []

        for title, href, anchor in candidates:
            alt_text = _alt_from_title(title)
            image_url = None

            # ── Strategy 1: grab image from the search card itself ────────────
            # PharmEasy renders a product thumbnail inside each result card.
            # The anchor wraps the card — walk up to the card container and
            # look for an <img> with a CDN src inside it.
            try:
                # Walk up the DOM to the product card container (usually 2-4 levels up)
                card = anchor
                for _ in range(5):
                    imgs_in_card = card.find_elements(By.TAG_NAME, "img")
                    for img in imgs_in_card:

                        src = img.get_attribute("src") or img.get_attribute("data-src")
                        if ("cdn01.pharmeasy.in" in src or "cdn02.pharmeasy.in" in src) and src.startswith("https://"):
                            image_url = src
                            break
                    if image_url:
                        break
                    # Move up one level
                    try:
                        card = card.find_element(By.XPATH, "..")
                    except Exception:
                        break
            except Exception:
                pass

            # ── Strategy 2: visit product page if card image not found ────────
            if not image_url:
                image_url = _fetch_image_from_product_page(driver, href, alt_text)
                # Navigate back to search results so remaining cards are still in DOM
                try:
                    driver.back()
                    time.sleep(1)
                except Exception:
                    pass

            results.append({
                "title": _alt_from_title(title),
                "url":   href,
                "image": image_url,
            })

        return {
            "medicine": medicine_name,
            "query":    query,
            "links":    results,
            "error":    None if results else "No results found",
        }

    except Exception as e:
        return {
            "medicine": medicine_name,
            "query":    query,
            "links":    [],
            "error":    str(e),
        }
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ── Parallel search for all medicines ────────────────────────────────────────

def search_all_parallel(medicines: list[dict], top_n: int = 3) -> list[dict]:
    """
    Launch one Chrome per medicine in parallel.
    medicines: [{"name": "Metformin", "dosage": "500mg", ...}, ...]
    Returns list of results in same order as input.
    """
    max_workers = min(len(medicines), 6)
    results_map = {}

    print(f"\n  🔍 Searching PharmEasy for {len(medicines)} medicine(s) in parallel...\n")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_med = {
            executor.submit(
                search_one,
                med["name"],
                med.get("dosage", ""),
                top_n
            ): med["name"]
            for med in medicines
        }

        for future in as_completed(future_to_med):
            med_name = future_to_med[future]
            try:
                result = future.result()
            except Exception as e:
                result = {
                    "medicine": med_name,
                    "query":    med_name,
                    "links":    [],
                    "error":    str(e),
                }
            results_map[med_name] = result

    return [results_map.get(med["name"], {
        "medicine": med["name"],
        "links":    [],
        "error":    "Not searched"
    }) for med in medicines]


# ── Format results for CLI display ───────────────────────────────────────────

def format_results(results: list[dict]) -> str:
    """Format search results for clean CLI display."""
    lines = []
    for result in results:
        med   = result["medicine"]
        links = result["links"]
        error = result["error"]

        lines.append(f"\n  💊 {med}")
        lines.append("  " + "─" * 50)

        if not links:
            lines.append(f"  ❌ Not found on PharmEasy")
            if error:
                lines.append(f"     ({error})")
        else:
            for i, link in enumerate(links, 1):
                title = link["title"][:60] + "..." if len(link["title"]) > 60 else link["title"]
                image = link.get("image") or "no image"
                lines.append(f"  {i}. {title}")
                lines.append(f"     {link['url']}")
                lines.append(f"     🖼  {image}")

    return "\n".join(lines)


# ── Quick test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_medicines = [
        {"name": "Metformin",    "dosage": "500mg"},
        {"name": "Atorvastatin", "dosage": "10mg"},
        {"name": "Amlodipine",   "dosage": "5mg"},
    ]

    start   = time.time()
    results = search_all_parallel(test_medicines)
    elapsed = time.time() - start

    print(format_results(results))
    print(f"\n  ⏱  Total time: {elapsed:.1f}s")