from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / ".codex" / "screenshots"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def check_dashboard(page, width: int, height: int, name: str) -> None:
    page.set_viewport_size({"width": width, "height": height})
    page.goto("http://127.0.0.1:5173/")
    page.get_by_role("heading", name="故障总览").wait_for(timeout=10_000)
    page.get_by_text("当前处置阶段").first.wait_for(timeout=10_000)
    page.screenshot(path=str(OUT_DIR / f"dashboard-{name}.png"), full_page=True)

    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"
    )
    if overflow:
        raise AssertionError(f"{name} viewport has horizontal overflow")


def check_routes(page, width: int, height: int, name: str) -> None:
    routes = {
        "/approvals": "恢复操作审批",
        "/scenarios": "故障场景",
        "/evaluations": "演练记录",
        "/system": "运行环境",
    }
    page.set_viewport_size({"width": width, "height": height})
    for route, heading in routes.items():
        page.goto(f"http://127.0.0.1:5173{route}")
        page.get_by_role("heading", name=heading).first.wait_for(timeout=10_000)
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"
        )
        if overflow:
            raise AssertionError(f"{name} viewport has horizontal overflow on {route}")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    for width, height, name in ((1440, 1000, "desktop"), (390, 900, "mobile")):
        page = browser.new_page(viewport={"width": width, "height": height})
        check_dashboard(page, width, height, name)
        check_routes(page, width, height, name)
        page.close()
    browser.close()

print("Visual smoke checks passed.")
