"""Browser end-to-end smoke test (Playwright). Needs: pip install playwright; a server running on 127.0.0.1:8766
with demo data (seed_demo), an Owner-group user smokeowner / Smoke-Test-Pass-77, and UPI enabled in Shop settings.
Development use only - never run against real data."""
import re, sys, json
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8766"
SHOTS = "/tmp"
results = []
def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

with sync_playwright() as p:
    b = p.chromium.launch()
    # ---------- phone-size customer flow
    ctx = b.new_context(viewport={"width": 375, "height": 800}, locale="ta-IN")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE + "/")
    check("home loads with mic button", page.locator("#mic-btn").is_visible())
    check("no horizontal overflow on phone", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
    check("unsupported-speech or ready banner shown", page.locator("#status-banner").inner_text().strip() != "")
    page.screenshot(path=f"{SHOTS}/home_mobile.png", full_page=True)

    page.fill("#speech-text", "ரெண்டு லக்ஸ் சோப்பு, half litre palm oil, 3 milk biscuits, 1 kilo seeni")
    page.click("#find-btn")
    page.wait_for_selector("#review-list .item-card")
    cards = page.locator("#review-list .item-card")
    check("4 review cards", cards.count() == 4, cards.count())
    check("all marked ready", page.locator("#review-list .tag.ok").count() == 4)
    page.screenshot(path=f"{SHOTS}/review_mobile.png", full_page=True)
    for _ in range(4):
        page.locator("#review-list .item-card button:has-text('Add to bill')").first.click()
        page.wait_for_timeout(400)
    page.wait_for_selector("#bill-lines .bill-line")
    check("bill has 4 lines", page.locator("#bill-lines .bill-line").count() == 4)
    total_text = page.locator("#bill-totals .grand").inner_text()
    # lux 2*40=80, palm 0.5*120=60, biscuits 3*10=30, sugar 1*45=45 -> 215.00
    check("server total is 215.00", "215.00" in total_text, total_text)
    page.screenshot(path=f"{SHOTS}/bill_mobile.png", full_page=True)

    # change quantity via + button, then remove
    page.locator("#bill-lines .bill-line").first.locator("button[aria-label='Increase quantity']").click()
    page.wait_for_timeout(600)
    check("qty change recalculated (255.00)", "255.00" in page.locator("#bill-totals .grand").inner_text())
    page.locator("#bill-lines .bill-line").nth(3).locator("button:has-text('Remove')").click()
    page.wait_for_timeout(600)
    check("remove works (3 lines)", page.locator("#bill-lines .bill-line").count() == 3)

    # conflict flow
    page.fill("#speech-text", "Half litre palm oil, two litres.")
    page.click("#find-btn")
    page.wait_for_selector("#review-list .item-card")
    check("conflict asks, does not guess", page.locator("#review-list .choice-btn").count() >= 2
          and page.locator("#review-list .tag.needs").count() == 1)
    page.locator("#review-list .choice-btn").filter(has_text="2 litres").first.click()
    page.wait_for_timeout(700)
    check("conflict resolved only after choice", page.locator("#review-list .item-card").count() == 0)

    # checkout
    page.click("#checkout-btn")
    page.wait_for_selector("#checkout-form", state="visible")
    check("payment options shown", page.locator("input[name=payment_method]").count() >= 1)
    page.fill("#customer-name", "Smoke Tester")
    page.fill("#customer-phone", "9876501234")
    page.check("#ful-delivery")
    page.wait_for_timeout(400)
    check("address field appears for delivery", page.locator("#delivery-address").is_visible())
    page.fill("#delivery-address", "12 Test Street, Chennai 600001")
    page.locator("input[name=payment_method][value=UPI]").check()
    page.screenshot(path=f"{SHOTS}/checkout_mobile.png", full_page=True)
    page.click("#place-order-btn")
    page.wait_for_url(re.compile(r"/order/.+placed=1"))
    body = page.inner_text("body")
    m = re.search(r"NG-\d{6}-[A-Z0-9]{5}", body)
    check("confirmation page with order number", m is not None)
    check("UPI instructions + not-paid wording", "demo@upi" in body and "Pending" in body)
    check("phone masked on confirmation", "9876501234" not in body)
    page.screenshot(path=f"{SHOTS}/confirm_mobile.png", full_page=True)
    order_no = m.group(0); order_url = page.url
    page.click("button:has-text('I have paid')")
    page.wait_for_load_state()
    check("claim paid -> awaiting verification, not paid", "Awaiting verification" in page.inner_text("body"))

    # ---------- unsupported voice message
    check("no JS errors on customer pages", not errors, errors[:3])

    # ---------- owner flow (desktop)
    octx = b.new_context(viewport={"width": 1280, "height": 900})
    op = octx.new_page()
    op.goto(BASE + "/owner/")
    check("owner area redirects to login", "/owner/login/" in op.url)
    op.fill("#id_username", "smokeowner"); op.fill("#id_password", "Smoke-Test-Pass-77")
    op.click("button[type=submit]")
    op.wait_for_url(BASE + "/owner/")
    check("dashboard lists new order", order_no in op.inner_text("body"))
    op.screenshot(path=f"{SHOTS}/dashboard_desktop.png", full_page=True)
    op.click(f"a:has-text('{order_no}')")
    op.wait_for_selector("text=Payment — UPI")
    op.click("button:has-text('Payment received')")
    check("owner verified UPI -> PAID", "Payment: Paid" in op.inner_text("body"))
    op.click("button:has-text('Accepted')")
    check("status -> Accepted", "Order: Accepted" in op.inner_text("body"))
    op.screenshot(path=f"{SHOTS}/order_owner_desktop.png", full_page=True)
    # print
    pp = octx.new_page()
    pp.goto(op.url.replace("/owner/orders/", "/owner/orders/").rstrip("/") + "/print/")
    check("print page has totals", "Total" in pp.inner_text("body") and order_no in pp.inner_text("body"))
    pp.emulate_media(media="print")
    check("toolbar hidden in print media", not pp.locator(".toolbar").is_visible())
    pp.pdf(path=f"{SHOTS}/bill_print.pdf", format="A4", print_background=True)
    # customer page now reflects the change
    page.goto(order_url)
    check("customer sees accepted + paid", "Accepted" in page.inner_text("body") and "Paid" in page.inner_text("body"))

    # ---------- desktop customer layout + unsupported speech message
    dctx = b.new_context(viewport={"width": 1366, "height": 800})
    dp = dctx.new_page(); dp.goto(BASE + "/")
    dp.fill("#speech-text", "2 lux soap")
    dp.click("#find-btn"); dp.wait_for_selector("#review-list .item-card")
    dp.screenshot(path=f"{SHOTS}/home_desktop.png", full_page=True)
    check("desktop no overflow", dp.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))

    # fake SpeechRecognition to exercise the voice code path
    vctx = b.new_context(viewport={"width": 375, "height": 800})
    vp = vctx.new_page()
    vp.add_init_script("""
      window.SpeechRecognition = function(){ this.start=()=>{ setTimeout(()=>{this.onstart&&this.onstart();
        this.onresult&&this.onresult({results:[Object.assign([{transcript:'two lux soap'}],{isFinal:true})]});
        setTimeout(()=>this.onend&&this.onend(),100)},50)}; this.stop=()=>{}; this.abort=()=>{}; };
    """)
    vp.goto(BASE + "/")
    vp.click("#mic-btn")
    vp.wait_for_selector("#review-list .item-card")
    check("voice path (mocked recogniser) -> review", vp.input_value("#speech-text") == "two lux soap")
    # denied mic
    dctx2 = b.new_context(viewport={"width": 375, "height": 800})
    dn = dctx2.new_page()
    dn.add_init_script("""
      window.SpeechRecognition = function(){ this.start=()=>{ setTimeout(()=>{ this.onerror&&this.onerror({error:'not-allowed'}); this.onend&&this.onend(); },50)}; this.stop=()=>{}; this.abort=()=>{}; };
    """)
    dn.goto(BASE + "/"); dn.click("#mic-btn"); dn.wait_for_timeout(400)
    check("mic denied -> clear message", "blocked" in dn.locator("#status-banner").inner_text().lower())
    b.close()

fails = [n for n, ok in results if not ok]
print(f"\n{len(results)-len(fails)}/{len(results)} checks passed")
sys.exit(1 if fails else 0)
