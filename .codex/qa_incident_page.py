import json
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts" / "incident-evidence-spine"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def overflow(page):
    return page.evaluate(
        """() => ({
          clientWidth: document.documentElement.clientWidth,
          scrollWidth: document.documentElement.scrollWidth,
          bodyScrollWidth: document.body.scrollWidth,
        })"""
    )


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    console_errors = []
    page_errors = []
    page = context.new_page()
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    seeded = context.request.post("http://127.0.0.1:8000/api/demo/seed")
    assert seeded.ok, f"seed failed: {seeded.status}"
    incident_id = seeded.json()["incident_ids"][0]
    incident_url = f"http://127.0.0.1:5173/incidents/{incident_id}"

    page.goto(incident_url)
    page.get_by_role("heading", name="处置证据链").wait_for()
    assert page.get_by_text("当前唯一决策").is_visible()
    assert page.get_by_text("当前影响").is_visible()
    assert page.get_by_text("首要判断").is_visible()
    desktop_overflow = overflow(page)
    assert desktop_overflow["scrollWidth"] <= desktop_overflow["clientWidth"]
    page.screenshot(path=str(ARTIFACT_DIR / "desktop-1440x900.png"), full_page=False)

    page.set_viewport_size({"width": 1280, "height": 720})
    page.get_by_role("heading", name="处置证据链").wait_for()
    spine_box = page.get_by_role("heading", name="处置证据链").bounding_box()
    assert spine_box and spine_box["y"] < 720, f"evidence spine starts below fold: {spine_box}"
    page.screenshot(path=str(ARTIFACT_DIR / "desktop-1280x720.png"), full_page=False)

    approve = page.get_by_role("button", name="批准恢复")
    assert approve.is_visible()
    approve.click()
    dialog = page.get_by_role("dialog", name="批准恢复操作")
    dialog.wait_for()
    assert dialog.is_visible()
    page.screenshot(path=str(ARTIFACT_DIR / "approval-dialog.png"), full_page=False)
    page.keyboard.press("Escape")
    assert not dialog.is_visible()
    assert approve.evaluate("element => element === document.activeElement")
    context.close()

    mobile_context = browser.new_context(viewport={"width": 390, "height": 844})
    mobile_page = mobile_context.new_page()
    mobile_page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    mobile_page.on("pageerror", lambda error: page_errors.append(str(error)))
    mobile_page.goto(incident_url)
    try:
        mobile_page.get_by_role("heading", name="处置证据链").wait_for(timeout=8_000)
    except PlaywrightTimeoutError:
        mobile_page.screenshot(path=str(ARTIFACT_DIR / "mobile-debug.png"), full_page=True)
        print(json.dumps({
            "mobile_body": mobile_page.locator("body").inner_text(),
            "console_errors": console_errors,
            "page_errors": page_errors,
        }, ensure_ascii=False))
        raise
    mobile_overflow = overflow(mobile_page)
    assert mobile_overflow["scrollWidth"] <= mobile_overflow["clientWidth"]
    assert mobile_overflow["bodyScrollWidth"] <= mobile_overflow["clientWidth"]
    mobile_page.screenshot(path=str(ARTIFACT_DIR / "mobile-390x844.png"), full_page=True)
    mobile_context.close()

    result = {
        "incident_id": incident_id,
        "desktop_overflow": desktop_overflow,
        "mobile_overflow": mobile_overflow,
        "console_errors": console_errors,
        "page_errors": page_errors,
        "screenshots": sorted(path.name for path in ARTIFACT_DIR.glob("*.png")),
    }
    print(json.dumps(result, ensure_ascii=False))
    assert not console_errors, console_errors
    assert not page_errors, page_errors
    browser.close()
