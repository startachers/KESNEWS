from __future__ import annotations

from playwright.async_api import Browser, Playwright, async_playwright

_playwright: Playwright | None = None
_browser: Browser | None = None

# Chromium's print-to-PDF keeps text as real vector glyphs regardless of scale,
# but box-shadow/gradient effects are rasterized at the context's device pixel
# ratio. 300/96 keeps those effects crisp when the PDF is printed on A4.
PDF_DEVICE_SCALE = 300 / 96


async def _get_browser() -> Browser:
    global _playwright, _browser
    if _browser is None:
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch()
    return _browser


async def close_pdf_browser() -> None:
    global _playwright, _browser
    if _browser is not None:
        await _browser.close()
        _browser = None
    if _playwright is not None:
        await _playwright.stop()
        _playwright = None


async def render_pdf(html: str) -> bytes:
    browser = await _get_browser()
    context = await browser.new_context(
        device_scale_factor=PDF_DEVICE_SCALE, java_script_enabled=False
    )
    try:
        page = await context.new_page()
        await page.set_content(html, wait_until="load")
        await page.emulate_media(media="print")
        return await page.pdf(
            format="A4",
            print_background=True,
            margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"},
        )
    finally:
        await context.close()
