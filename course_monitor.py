"""
IITM Course Vacancy Monitor
============================
Logs into workflow.iitm.ac.in, navigates to Add/Drop → View Electives,
reads the iframe listing all elective courses with vacancies, filters for
GS (GN-prefixed) courses, and prints available ones.

Runs as a Hermes cron job every 5 minutes. When a new GS course appears
with vacancies > 0, it sends an email via himalaya to ce23b115@smail.iitm.ac.in.
"""
import asyncio, json, os, sys, subprocess, smtplib
from email.mime.text import MIMEText
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

# --- Config ---
LDAP_USER = os.getenv("IITM_LDAP_USER", "ce23b115")
LDAP_PASS = os.getenv("IITM_LDAP_PASS", "Vahid@@@2005")
SMAIL_PASS = os.getenv("SMAIL_PASS", "shcy dsbp imof eywa")

PROXY = {
    "server": "https://remote.iitm.ac.in:8372",
    "username": LDAP_USER,
    "password": LDAP_PASS,
}
FIREFOX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0"
STATE_FILE = Path(__file__).parent / "last_gs_state.json"
GS_PREFIXES = ["GN", "ID", "CE"]  # Course prefixes to monitor
# Exact courses to monitor — only these, no other GN courses
MONITORED_GN   = {"GN6002", "GN6101", "GN6120"}   # alert on any vacancy change
THRESHOLD_COURSES = {
    "CE5010": 10,   # alert when vacancies < 10
    "ID4101": 20,   # alert when vacancies < 20
}
APPEAR_COURSES = {"CE5470", "BT6220", "HS1091", "HS1090"}  # alert the instant it appears with any vacancy > 0
ALL_WATCHED = MONITORED_GN | set(THRESHOLD_COURSES) | APPEAR_COURSES


async def login(page):
    """Login to IITM student portal. Returns True on success."""
    await page.goto("https://workflow.iitm.ac.in/student/", timeout=30000)
    await page.wait_for_load_state("networkidle", timeout=15000)
    captcha = await page.evaluate("document.getElementById('HiddenCaptcha')?.value || ''")
    if not captcha:
        return False
    await page.fill("#txtUserName", PROXY["username"])
    await page.fill("#txtPassword", PROXY["password"])
    await page.fill("#txtCaptcha", captcha)
    await page.check("#chkRemember")
    await page.click("#Login")
    await page.wait_for_load_state("networkidle", timeout=30000)
    await asyncio.sleep(2)
    return "StudentBasicInfo" in page.url


async def get_elective_courses(page):
    """Navigate to Add/Drop → View Electives iframe and extract courses."""
    # Wait until __doPostBack is defined
    try:
        await page.wait_for_function("typeof __doPostBack === 'function'", timeout=15000)
    except Exception:
        # Fallback reload if it failed to load scripts
        await page.reload()
        await page.wait_for_load_state("networkidle", timeout=15000)
        await page.wait_for_function("typeof __doPostBack === 'function'", timeout=15000)
        
    # Go to Add/Drop page
    await page.evaluate("__doPostBack('ctl00$AddDropCoursesLink','')")
    await page.wait_for_load_state("networkidle", timeout=30000)
    await asyncio.sleep(2)

    # Click View Electives to open the modal with iframe
    await page.wait_for_function("typeof __doPostBack === 'function'", timeout=15000)
    await page.evaluate("__doPostBack('ctl00$MainContent$btnViewAvailablityElec','')")
    await asyncio.sleep(5)

    # Navigate directly to the electives iframe page (faster + more reliable)
    await page.goto(
        "https://workflow.iitm.ac.in/student/ReportPages/ElectiveCoursesViewAddDrop.aspx",
        timeout=30000
    )
    await page.wait_for_load_state("networkidle", timeout=15000)
    await asyncio.sleep(2)

    courses = await page.evaluate("""() => {
        const rows = document.querySelectorAll('tr');
        const results = [];
        for (const row of rows) {
            const cells = row.querySelectorAll('td');
            if (cells.length >= 5) {
                const texts = Array.from(cells).map(c => c.innerText?.trim());
                // Course rows: column 0 is Course No (e.g. AE5510, CE5010)
                if (texts[0] && /^[A-Z]{2}[0-9]/.test(texts[0])) {
                    results.push({
                        course_no: texts[0],
                        course_name: texts[1] || '',
                        slot: texts[2] || '',
                        credit: texts[3] || '',
                        vacancies: texts[4] || '0'
                    });
                }
            }
        }
        return results;
    }""")
    return courses


def filter_gs_courses(courses):
    """Filter only the exact watched courses."""
    gs = []
    for c in courses:
        cno = c["course_no"]
        if cno not in ALL_WATCHED:
            continue
        try:
            c["vacancies_int"] = int(c["vacancies"])
        except ValueError:
            c["vacancies_int"] = 0
        gs.append(c)
    return gs


def load_previous_state():
    """Load previous scan state."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(gs_courses):
    """Save current watched course state."""
    state = {f"{c['course_no']}_{c['slot']}": c["vacancies"] for c in gs_courses}
    STATE_FILE.write_text(json.dumps(state, indent=2))
    return state


def detect_changes(gs_courses, prev_state):
    """Detect changes for all watched courses.

    - GN6002, GN6101, GN6120: alert on ANY vacancy change (appear, disappear, count change)
    - CE5010: alert when vacancies < 10
    - ID4101: alert when vacancies < 20
    - CE5470: alert the instant it appears with vacancies > 0
    """
    alerts = []
    current_keys = set()

    for c in gs_courses:
        cno = c["course_no"]
        slot = c["slot"]
        vac = c["vacancies_int"]
        state_key = f"{cno}_{slot}"
        current_keys.add(state_key)

        prev_vac_str = prev_state.get(state_key) or prev_state.get(cno)
        prev_vac = None
        if prev_vac_str is not None:
            try:
                prev_vac = int(prev_vac_str)
            except ValueError:
                pass

        if cno in MONITORED_GN:
            if prev_vac is None:
                alerts.append(f"🆕 NEW GN COURSE: {cno} — {c['course_name']} | Slot: {slot} | Vacancies: {vac}")
            elif prev_vac != vac:
                alerts.append(f"🔄 GN VACANCY CHANGE: {cno} — {c['course_name']} | Slot: {slot} | {vac} (was {prev_vac})")

        elif cno in APPEAR_COURSES:
            if (prev_vac is None or prev_vac == 0) and vac > 0:
                alerts.append(f"🚨 {cno} APPEARED: {c['course_name']} | Slot: {slot} | Vacancies: {vac} — Register NOW!")

        elif cno in THRESHOLD_COURSES:
            threshold = THRESHOLD_COURSES[cno]
            if vac < threshold:
                if prev_vac is None:
                    alerts.append(f"🚨 {cno} CRITICAL: Vacancies are {vac} (under threshold of {threshold}!)")
                elif prev_vac >= threshold:
                    alerts.append(f"🚨 {cno} FELL BELOW THRESHOLD: Dropped to {vac} (was {prev_vac})")
                elif prev_vac != vac:
                    alerts.append(f"🚨 {cno} VACANCY UPDATE: Changed to {vac} (was {prev_vac})")

    # Courses that disappeared since last check
    for state_key, prev_vac_str in prev_state.items():
        if state_key in current_keys:
            continue
        cno, slot = state_key.split("_", 1) if "_" in state_key else (state_key, "?")
        try:
            prev_vac = int(prev_vac_str)
        except ValueError:
            prev_vac = 0
        if prev_vac > 0:
            if cno in MONITORED_GN:
                alerts.append(f"🔄 GN FILLED: {cno} (Slot: {slot}) disappeared/filled to 0 (was {prev_vac})")
            elif cno in THRESHOLD_COURSES and prev_vac >= THRESHOLD_COURSES[cno]:
                alerts.append(f"🚨 {cno} FELL BELOW THRESHOLD: Filled to 0 (was {prev_vac})")
            elif cno in APPEAR_COURSES:
                alerts.append(f"🔄 {cno} FILLED: (Slot: {slot}) filled to 0 (was {prev_vac})")

    return alerts


def send_email_alert(subject, body):
    """Send email alert via Google SMTP (Smail runs on Google Workspace)."""
    smtp_user = f"{LDAP_USER}@smail.iitm.ac.in"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = smtp_user

    try:
        print("Connecting to SMTP server...")
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.starttls()
            server.login(smtp_user, SMAIL_PASS)
            server.sendmail(smtp_user, [smtp_user], msg.as_string())
        print("📧 Email alert sent successfully!")
    except Exception as e:
        print(f"⚠️ Email sending failed: {e}")


async def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if "--test-email" in sys.argv:
        print(f"[{now}] Processing test email alert...")
        subject = "IITM Course Monitor: Test Email Notification"
        body = (
            "Hi Vahid,\n\n"
            "This is a test email confirmation from your IITM Course Monitor script.\n"
            "If you are reading this, the himalaya client is working and connected!\n\n"
            "Best regards,\n"
            "IITM Course Monitor Script"
        )
        send_email_alert(subject, body)
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            proxy=PROXY,
            args=["--ignore-certificate-errors"],
        )
        context = await browser.new_context(ignore_https_errors=True, user_agent=FIREFOX_UA)
        page = await context.new_page()

        try:
            if not await login(page):
                print(f"[{now}] ❌ Login failed")
                sys.exit(1)

            courses = await get_elective_courses(page)
            if not courses:
                print(f"[{now}] ❌ No courses found (page may have not loaded)")
                sys.exit(1)

            gs_courses = filter_gs_courses(courses)
            prev_state = load_previous_state()
            alerts = detect_changes(gs_courses, prev_state)
            new_state = save_state(gs_courses)

            force_email = "--force-email" in sys.argv
            
            # If force-email is set, compile all current course states into an alert
            if force_email:
                status_header = f"🔍 MANUAL STATUS CHECK — {now}"
                status_lines = []
                for c in gs_courses:
                    status = f"✅ {c['vacancies']}" if c['vacancies_int'] > 0 else "❌ 0"
                    status_lines.append(f"  {c['course_no']} | {c['course_name'][:50]} | Slot: {c['slot']} | {status}")
                status_report = "\n".join(status_lines)
                
                # Append to alerts
                alerts_summary = f"\n\n🚨 ACTIVE CHANGES DETECTED:\n" + "\n".join(alerts) if alerts else "\n\n(No new state changes detected since last check)"
                alerts = [f"{status_header}\n\nCurrent general studies and tracked electives vacancies:\n{status_report}{alerts_summary}"]

            # --- OUTPUT & EMAIL ALERT ---
            if alerts:
                alert_text = "\n".join(alerts)
                subject = f"IITM Course Monitor: Live Status Update" if force_email else f"IITM Course Alert: Slot Available!"
                body = (
                    f"Hi Vahid,\n\n"
                    f"The following general studies or tracked course update(s) were triggered:\n\n"
                    f"{alert_text}\n\n"
                    f"Log in now to register: https://workflow.iitm.ac.in/student/\n\n"
                    f"Best regards,\n"
                    f"IITM Course Monitor Script"
                )
                print(f"🚨 COURSE MONITOR ALERT — {now}")
                print("=" * 60)
                print(alert_text)
                print("=" * 60)
                print("Sending email alert via himalaya...")
                send_email_alert(subject, body)
            else:
                # No change — silent (cron won't send notification for empty output)
                # But print for manual runs
                if "--verbose" in sys.argv:
                    print(f"[{now}] No new GS courses. Total electives: {len(courses)}, GS courses: {len(gs_courses)}")
                    for c in gs_courses:
                        status = f"✅ {c['vacancies']}" if c['vacancies_int'] > 0 else "❌ 0"
                        print(f"  {c['course_no']} | {c['course_name'][:55]} | Slot: {c['slot']} | {status}")

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
