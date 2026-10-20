"""Submit the real setup HTML in a browser, using synthetic credentials only.

Maintainer/CI test: requires Go and Python Playwright. Customers need neither.
Unlike the HTTP acceptance harness, this never supplies an Origin header.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", choices=["chromium", "edge"], default="chromium")
    args = parser.parse_args()
    go = os.environ.get("CREATIVE_KIT_BUILD_GO") or shutil.which("go")
    if not go:
        raise SystemExit("Go is required for this maintainer test.")
    with tempfile.TemporaryDirectory(prefix="creative-kit-browser-") as directory:
        url_file = Path(directory) / "url"
        process = subprocess.Popen(
            [go, "test", "-run", "^TestBrowserSetupForm$", "-count=1", "-v"],
            cwd=ROOT / "native-launcher",
            env={**os.environ, "CREATIVE_KIT_BROWSER_URL_FILE": str(url_file)},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        )
        try:
            deadline = time.monotonic() + 90
            while not url_file.exists():
                if process.poll() is not None:
                    raise AssertionError(process.communicate()[0])
                if time.monotonic() > deadline:
                    raise AssertionError("Setup browser fixture did not start")
                time.sleep(0.1)
            with sync_playwright() as playwright:
                options = {"headless": True}
                if args.browser == "edge":
                    options["channel"] = "msedge"
                browser = playwright.chromium.launch(**options)
                try:
                    page = browser.new_page()
                    page.goto(url_file.read_text().strip())
                    page.get_by_label("ModelArk API Key", exact=True).fill("synthetic-browser-api-key")
                    page.get_by_label("ModelArk 项目", exact=True).fill("browser-regression")
                    with page.expect_navigation(wait_until="domcontentloaded") as navigation:
                        page.get_by_role("button", name="保存配置并准备工具", exact=True).click()
                    response = navigation.value
                    assert response is not None and response.status == 200, page.locator("body").inner_text()
                    expect(page.get_by_role("status")).to_contain_text("配置已保存在本机")
                    assert "synthetic-browser-api-key" not in page.content(), "Saved page echoed a credential"
                    print(f"PASS: {args.browser} {browser.version}: normal setup form saved synthetic credentials", flush=True)
                finally:
                    browser.close()
            output, _ = process.communicate(timeout=15)
            print(output, end="")
            assert process.returncode == 0, "Go fixture rejected the browser-generated Origin or saved settings"
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


if __name__ == "__main__":
    main()
