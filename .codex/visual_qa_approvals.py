"""审批视觉回归；启动 Vite 前设置 VITE_SENTINEL_ROLE=approver。"""

from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:5173"
OUTPUT_DIR = Path(".codex/visual-qa")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    browser_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.on("console", lambda message: browser_errors.append(f"console:{message.type}:{message.text}") if message.type == "error" else None)
        page.on("pageerror", lambda error: browser_errors.append(f"pageerror:{error}"))

        page.goto(BASE_URL)
        page.get_by_role("heading", name="事故指挥室").wait_for()
        page.get_by_role("button", name="载入演示事故").click()
        page.get_by_text("事故队列").wait_for()

        page.goto(f"{BASE_URL}/approvals")
        page.get_by_role("heading", name="审批队列").wait_for()
        page.screenshot(path=str(OUTPUT_DIR / "approvals-desktop.png"), full_page=True)
        pending_link = page.get_by_role("link", name="查看上下文").first
        pending_link.wait_for()
        pending_link.click()
        page.get_by_text("INCIDENT / CONTROL ROOM").wait_for()
        page.screenshot(path=str(OUTPUT_DIR / "incident-desktop.png"), full_page=True)

        approve_button = page.get_by_role("button", name="审核批准").first
        approve_button.wait_for()
        approve_button.click()
        page.get_by_role("dialog").wait_for()
        page.screenshot(path=str(OUTPUT_DIR / "approval-confirm-desktop.png"), full_page=True)
        page.get_by_role("button", name="取消").click()

        mobile = browser.new_context(viewport={"width": 390, "height": 844})
        mobile_page = mobile.new_page()
        mobile_page.goto(f"{BASE_URL}/approvals")
        mobile_page.get_by_role("heading", name="审批队列").wait_for()
        mobile_page.screenshot(path=str(OUTPUT_DIR / "approvals-mobile.png"), full_page=True)
        overflow = mobile_page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        print(f"mobile_horizontal_overflow={overflow}")
        print(f"browser_errors={browser_errors}")
        print(f"screenshots={OUTPUT_DIR.resolve()}")
        mobile.close()
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
