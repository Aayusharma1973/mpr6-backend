"""
pharmeasy_scraper.py — Parallel Selenium scraper for PharmEasy
Launches one headless Chrome per medicine simultaneously.
Returns top 3 product page links per medicine.

Works on:
  - Windows (local dev)
  - GCP Linux VM (headless)

Requirements:
  pip install selenium webdriver-manager
"""

import time
import re
import random
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
    
    # Use a more modern and random-ish user agent to avoid detection
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ]
    opts.add_argument(f"user-agent={random.choice(user_agents)}")

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


# ── Single medicine search ────────────────────────────────────────────────────

def search_one(medicine_name: str, dosage: str = "", top_n: int = 3) -> dict:
    """
    Search PharmEasy for one medicine.
    """
    query = f"{medicine_name} {dosage}".strip()
    url   = f"https://pharmeasy.in/search/all?name={query.replace(' ', '%20')}"

    # Regex for valid PharmEasy product links
    # Matches /online-medicine-order/some-product-name-12345
    # Optional trailing slash or query params
    PRODUCT_REGEX = r'/online-medicine-order/[a-z0-9-]+-\d+/?(\?.*)?$'

    driver = None
    try:
        # Add random sleep before starting to stagger parallel requests
        time.sleep(random.uniform(0.5, 2.5))
        
        driver = _make_driver()
        driver.get(url)

        # Wait for product cards
        wait = WebDriverWait(driver, 15)

        # Custom wait: wait until at least one link matching our PRODUCT_REGEX appears
        def product_link_present(d):
            links = d.find_elements(By.CSS_SELECTOR, "a[href*='online-medicine-order']")
            for l in links:
                href = l.get_attribute("href") or ""
                if re.search(PRODUCT_REGEX, href):
                    return True
            return False

        try:
            wait.until(product_link_present)
        except Exception:
            # If our specific wait fails, the page might just be slow or have no results
            time.sleep(2)

        # PharmEasy search results container selectors
        RESULT_CONTAINER_SELECTORS = [
            "div.search-listing-page",
            "div[class*='search-listing']",
            "div[class*='product-list']",
            "div[class*='ProductList']",
            "main",
        ]

        # Find the narrowest container that holds the search results
        container = None
        for selector in RESULT_CONTAINER_SELECTORS:
            els = driver.find_elements(By.CSS_SELECTOR, selector)
            if els:
                container = els[0]
                break

        # Grab product links scoped to the container (or full page as last resort)
        scope = container if container else driver
        anchors = scope.find_elements(
            By.CSS_SELECTOR, "a[href*='online-medicine-order']"
        )

        seen_urls = set()
        results   = []

        for anchor in anchors:
            href  = anchor.get_attribute("href") or ""
            title = anchor.get_attribute("title") or anchor.text.strip()

            # Clean up title
            title = re.sub(r"\s+", " ", title).strip()

            if not href or href in seen_urls:
                continue

            # Verify it's a real product page
            if not re.search(PRODUCT_REGEX, href):
                continue

            if not title:
                title = medicine_name

            # Normalize URL (remove query params for deduplication)
            base_url = href.split("?")[0].rstrip("/")
            if base_url in seen_urls:
                continue
                
            seen_urls.add(base_url)
            results.append({"title": title, "url": href})

            if len(results) >= top_n:
                break

        error_msg = None
        if not results:
            # Diagnose why nothing was found
            page_title = driver.title
            if "Robot" in page_title or "Captcha" in page_title:
                error_msg = "Bot detection / Captcha triggered"
            else:
                error_msg = "No results found on page"

        return {
            "medicine": medicine_name,
            "query":    query,
            "links":    results,
            "error":    error_msg,
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
    # Cap parallelism — too many Chrome instances will crash low-RAM machines
    # 6 is safe on 8GB+ RAM; GCP n1-standard-2 (7.5GB) handles it fine
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

    # Return in original prescription order
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
                lines.append(f"  {i}. {title}")
                lines.append(f"     {link['url']}")

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