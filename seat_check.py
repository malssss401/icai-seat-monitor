"""
ICAI Seat Monitor — Production Script
=======================================
City   : CHENNAI
Course : AICITSS - Advanced Information Technology

Behaviour:
  • Seats found       → Pushover alert → disable this workflow (stops auto-runs)
  • Script/site error → Pushover alert → disable this workflow
  • 0 seats           → silent exit (cron re-runs in 5 min)
  • No records found  → silent exit (cron re-runs in 5 min)

"Stop after notification" is implemented by calling the GitHub API to
disable the workflow file.  The user re-enables it manually from the
Actions tab when they want monitoring to resume.

Run history: every execution writes one row to $GITHUB_STEP_SUMMARY,
which is visible in the Actions tab → click any run → Summary tab.
"""

import os
import sys
import time
import requests
from datetime import datetime, timezone, timedelta

# ── IST = UTC + 5:30 ──────────────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))

# ── Config ─────────────────────────────────────────────────────────────────────
URL         = "https://www.icaionlineregistration.org/launchbatchdetail.aspx"
REGION_VAL  = "4"          # Southern
POU_LABEL   = "CHENNAI"
COURSE_NAME = "AICITSS - Advanced Information Technology"

# ── Credentials ────────────────────────────────────────────────────────────────
PUSHOVER_USER  = os.environ.get("PUSHOVER_USER", "")
PUSHOVER_TOKEN = os.environ.get("PUSHOVER_TOKEN", "")

# ── GitHub API (auto-provided by Actions runner, no manual secret needed) ──────
GITHUB_TOKEN      = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "")   # e.g. "yourname/icai-monitor"
WORKFLOW_FILE     = "monitor.yml"                              # must match your workflow filename

# ── Run timestamp (UTC) ────────────────────────────────────────────────────────
RUN_TIME = datetime.now(IST).strftime("%d-%m-%Y %I:%M %p IST")


# ── Stealth loader ─────────────────────────────────────────────────────────────
def _load_stealth():
    for name in ("stealth_sync", "stealth"):
        try:
            import playwright_stealth as _m
            fn = getattr(_m, name, None)
            if callable(fn):
                return fn
        except ImportError:
            pass
    return None


# ── GitHub Step Summary ────────────────────────────────────────────────────────
def write_summary(status: str, detail: str) -> None:
    """
    Appends one row to the GitHub Actions Step Summary table.
    Visible at: Actions tab → click any run → Summary tab.
    If $GITHUB_STEP_SUMMARY is not set (local run), prints to stdout instead.
    """
    row = f"| {RUN_TIME} | {POU_LABEL} | {COURSE_NAME[:35]} | {status} | {detail} |\n"
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            # Write table header only once per job (file is empty at start)
            file_empty = os.path.getsize(summary_path) == 0
            with open(summary_path, "a") as f:
                if file_empty:
                    f.write("## ICAI Seat Monitor — Run Log\n\n")
                    f.write("| Time (UTC) | City | Course | Status | Detail |\n")
                    f.write("|---|---|---|---|---|\n")
                f.write(row)
        except Exception as e:
            print(f"Summary write error: {e}")
    else:
        print(f"SUMMARY → {row.strip()}")


# ── Pushover ───────────────────────────────────────────────────────────────────
def send_push(message: str, title: str = "ICAI Monitor") -> bool:
    if not PUSHOVER_USER or not PUSHOVER_TOKEN:
        print("⚠️  Pushover secrets missing — cannot send notification.")
        return False
    try:
        r = requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": PUSHOVER_TOKEN, "user": PUSHOVER_USER,
                  "title": title, "message": message},
            timeout=15,
        )
        success = r.status_code == 200
        print(f"Pushover → HTTP {r.status_code}" + ("" if success else f": {r.text}"))
        return success
    except Exception as e:
        print(f"Pushover error: {e}")
        return False


# ── Disable workflow ───────────────────────────────────────────────────────────
def disable_workflow() -> None:
    """
    Calls the GitHub REST API to disable this workflow file.
    After this, the */5 cron will no longer trigger new runs.
    The user re-enables it from: Actions tab → select workflow → '...' menu → Enable.
    Requires the workflow to have: permissions: actions: write
    """
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        print("⚠️  GITHUB_TOKEN or GITHUB_REPOSITORY not set — cannot disable workflow.")
        return
    url = (
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}"
        f"/actions/workflows/{WORKFLOW_FILE}/disable"
    )
    try:
        r = requests.put(
            url,
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15,
        )
        if r.status_code == 204:
            print("✅  Workflow disabled — no further automatic runs until re-enabled.")
        else:
            print(f"⚠️  Workflow disable returned HTTP {r.status_code}: {r.text}")
    except Exception as e:
        print(f"Workflow disable error: {e}")


# ── Screenshot ─────────────────────────────────────────────────────────────────
def screenshot(page, path: str) -> None:
    try:
        page.screenshot(path=path, full_page=True)
        print(f"📸  {path}")
    except Exception as e:
        print(f"Screenshot error: {e}")


# ── Course selector ────────────────────────────────────────────────────────────
def select_course(page, course_sel: str, course_name: str) -> str:
    options = page.eval_on_selector(
        course_sel,
        "el => Array.from(el.options).map(o => ({value: o.value, text: o.text.trim()}))"
    )
    print("   Course options available:")
    for opt in options:
        print(f"     {opt['value']}  →  '{opt['text']}'")

    target = course_name.strip().lower()
    match  = next((o for o in options if o["text"].lower() == target), None)
    if not match:
        match = next((o for o in options if target in o["text"].lower()), None)
        if match:
            print(f"   ⚠️  Partial match used: '{match['text']}'")
    if not match:
        raise ValueError(f"Course '{course_name}' not found. Available: {[o['text'] for o in options]}")

    page.select_option(course_sel, value=match["value"])
    print(f"   ✅  Course: '{match['text']}'")
    return match["text"]


# ── Main check ─────────────────────────────────────────────────────────────────
def run_check():
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    stealth_fn = _load_stealth()
    print(f"\n{'─'*55}")
    print(f"  Run  : {RUN_TIME}")
    print(f"  City : {POU_LABEL}  |  Course: {COURSE_NAME}")
    print(f"{'─'*55}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        page.route(
            "**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf,otf,css}",
            lambda route: route.abort(),
        )
        if stealth_fn:
            stealth_fn(page)

        try:
            # ── 1. Load ────────────────────────────────────────────────────
            print("[1/4] Loading page …")
            page.goto(URL, wait_until="domcontentloaded", timeout=60_000)

            # ── 2. Region → postback reload ────────────────────────────────
            print("[2/4] Selecting Region …")
            page.wait_for_selector("select[id*='reg']", state="visible", timeout=15_000)
            page.select_option("select[id*='reg']", value=REGION_VAL)
            page.wait_for_load_state("domcontentloaded", timeout=30_000)
            time.sleep(2)

            # ── 3. POU ─────────────────────────────────────────────────────
            pou_sel    = "select[id*='POU'], select[id*='pou'], select[id*='Pou']"
            course_sel = "select[id*='Course'], select[id*='course']"

            print(f"[3/4] Selecting POU '{POU_LABEL}' …")
            try:
                page.select_option(pou_sel, label=POU_LABEL, timeout=10_000)
            except Exception:
                # Case-insensitive JS fallback
                matched = page.eval_on_selector(
                    pou_sel,
                    f"""el => {{
                        const opt = Array.from(el.options).find(
                            o => o.text.trim().toUpperCase() === '{POU_LABEL.upper()}'
                        );
                        if (opt) {{ el.value = opt.value; return opt.text.trim(); }}
                        return null;
                    }}"""
                )
                if not matched:
                    pou_opts = page.eval_on_selector(
                        pou_sel,
                        "el => Array.from(el.options).map(o => o.text.trim())"
                    )
                    raise ValueError(f"City '{POU_LABEL}' not found. Available: {pou_opts}")

            # ── 4. Course + Get List ───────────────────────────────────────
            print(f"[4/4a] Selecting course …")
            selected_course = select_course(page, course_sel, COURSE_NAME)

            print("[4/4b] Clicking Get List …")
            page.click("input[value='Get List']")
            page.wait_for_load_state("domcontentloaded", timeout=60_000)
            time.sleep(3)

            # ── Parse ──────────────────────────────────────────────────────
            page_text  = page.inner_text("body").lower()
            no_records = "no records found" in page_text

            rows = page.query_selector_all("tr")
            data = []
            for row in rows:
                cells = [c.inner_text().strip() for c in row.query_selector_all("td")]
                if cells:
                    data.append(cells)

            batches_with_seats = []
            batches_zero       = []

            for row in data:
                if len(row) < 2 or not row[1].isdigit():
                    continue
                seats = int(row[1])
                entry = {
                    "batch": row[0],
                    "seats": seats,
                    "dates": f"{row[2] if len(row)>2 else ''} – {row[3] if len(row)>3 else ''}",
                    "time":  row[4] if len(row) > 4 else "",
                }
                if seats > 0:
                    batches_with_seats.append(entry)
                else:
                    batches_zero.append(row[0])

            print(f"   Batches with seats : {len(batches_with_seats)}")
            print(f"   Batches zero seats : {len(batches_zero)}")
            print(f"   No records flag    : {no_records}")

            # ══════════════════════════════════════════════════════════════
            # OUTCOME HANDLING
            # ══════════════════════════════════════════════════════════════

            if batches_with_seats:
                # ── SEATS FOUND → notify + stop ────────────────────────────
                lines = [
                    f"• {b['batch']}\n"
                    f"  Seats : {b['seats']}  |  {b['dates']}\n"
                    f"  Time  : {b['time']}"
                    for b in batches_with_seats
                ]
                msg = (
                    f"🚨 Seats Available — {POU_LABEL}!\n"
                    f"{selected_course}\n\n"
                    + "\n\n".join(lines)
                )
                if batches_zero:
                    msg += f"\n\n(+ {len(batches_zero)} batch(es) fully booked)"

                detail = f"{sum(b['seats'] for b in batches_with_seats)} seat(s) across {len(batches_with_seats)} batch(es)"
                print(f"\n🚨  {detail}")

                send_push(msg, title=f"ICAI — {POU_LABEL} Seats Open!")
                write_summary("🚨 SEATS FOUND", detail)
                disable_workflow()   # Stop further automatic runs

            elif no_records:
                # ── NO BATCHES SCHEDULED → silent ──────────────────────────
                print("   ℹ️   No batches scheduled — silent exit.")
                write_summary("ℹ️ No records", "Site returned no batches for this search")

            else:
                # ── ALL SEATS = 0 → silent ─────────────────────────────────
                total = len(batches_zero)
                print(f"   ℹ️   {total} batch(es) found, all seats = 0 — silent exit.")
                write_summary("⭕ 0 seats", f"{total} batch(es) fully booked")

        except Exception as exc:
            # ── UNEXPECTED ERROR → notify + stop ───────────────────────────
            err_str = str(exc)
            print(f"\n❌  {err_str}")
            screenshot(page, "error_screenshot.png")

            send_push(
                f"⚠️ Monitor error — {POU_LABEL}\n\n{err_str[:200]}\n\n"
                f"Check GitHub Actions log for details.",
                title="ICAI Monitor — Error"
            )
            write_summary("❌ ERROR", err_str[:80])
            disable_workflow()   # Stop on unexpected errors too

        finally:
            browser.close()


if __name__ == "__main__":
    run_check()
