"""
IITM Course Vacancy Monitor - GitHub Actions Edition
======================================================
Logs into workflow.iitm.ac.in via remote.iitm.ac.in proxy.
Checks for General Studies (GN) course vacancy changes, ID4101 vacancies, and CE5010 vacancies.
Sends email alerts via Gmail SMTP (Smail) using GitHub Secrets.
"""
import os
import sys
import json
import asyncio
import smtplib
from datetime import datetime
from pathlib import Path
from email.mime.text import MIMEText
from playwright.async_api import async_playwright

# --- Inputs from environment (GitHub Secrets) ---
LDAP_USER = os.getenv("IITM_LDAP_USER")
LDAP_PASS = os.getenv("IITM_LDAP_PASS")
SMAIL_PASS = os.getenv("SMAIL_PASS")

if not all([LDAP_USER, LDAP_PASS, SMAIL_PASS]):
    print("❌ ERROR: Missing required environment secrets (IITM_LDAP_USER, IITM_LDAP_PASS, SMAIL_PASS)")
    sys.exit(1)

PROXY = {
    "server": "https://remote.iitm.ac.in:8372",
    "username": LDAP_USER,
    "password": LDAP_PASS,
}
FIREFOX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0"
STATE_FILE = Path(__file__).parent / "last_gs_state.json"
GS_PREFIXES = ["GN", "ID", "CE"]
SPECIFIC_COURSES = ["ID4101", "CE5010"]


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


async def login(page):
    """Login to IITM student portal. Returns True on success."""
    await page.goto("https://workflow.iitm.ac.in/student/", timeout=30000)
    await page.wait_for_load_state("networkidle", timeout=15000)
    captcha = await page.evaluate("document.getElementById('HiddenCaptcha')?.value || ''")
    if not captcha:
        return False
    await page.fill("#txtUserName", LDAP_USER)
    await page.fill("#txtPassword", LDAP_PASS)
    await page.fill("#txtCaptcha", captcha)
    await page.check("#chkRemember")
    await page.click("#Login")
    await page.wait_for_load_state("networkidle", timeout=30000)
    await asyncio.sleep(2)
    return "StudentBasicInfo" in page.url


async def get_elective_courses(page):
    """Navigate directly to the electives iframe page."""
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
    """Filter for GS (GN-prefixed) courses or the specific target courses."""
    gs = []
    for c in courses:
        cno = c["course_no"]
        is_gn = cno.startswith("GN")
        is_specific = cno in SPECIFIC_COURSES
        
        if not (is_gn or is_specific):
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
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(gs_courses):
    """Save current GS course state."""
    state = {f"{c['course_no']}_{c['slot']}": c["vacancies"] for c in gs_courses}
    STATE_FILE.write_text(json.dumps(state, indent=2))
    return state


def detect_changes(gs_courses, prev_state):
    """Detect new courses, changes in vacancy counts, or courses that disappeared."""
    alerts = []
    current_keys = set()
    
    # 1. Process courses that are currently visible
    for c in gs_courses:
        cno = c["course_no"]
        slot = c["slot"]
        vac = c["vacancies_int"]
        state_key = f"{cno}_{slot}"
        current_keys.add(state_key)
        
        prev_vac_str = prev_state.get(state_key)
        
        # Fallback: check by cno
        if prev_vac_str is None:
            prev_vac_str = prev_state.get(cno)
        
        # Parse previous vacancy
        if prev_vac_str is not None:
            try:
                prev_vac = int(prev_vac_str)
            except ValueError:
                prev_vac = None
        else:
            prev_vac = None
            
        # Check GN courses
        if cno.startswith("GN"):
            if prev_vac is None:
                alerts.append(f"🆕 NEW GN COURSE: {cno} — {c['course_name']} | Slot: {slot} | Vacancies: {vac}")
            elif prev_vac != vac:
                alerts.append(f"🔄 GN VACANCY CHANGE: {cno} — {c['course_name']} | Slot: {slot} | Vacancies: {vac} (was {prev_vac})")
                
        # Check ID4101
        elif cno == "ID4101":
            threshold = 20
            if vac < threshold:
                if prev_vac is None:
                    alerts.append(f"🚨 ID4101 CRITICAL: Vacancies are {vac} (under threshold of {threshold}!)")
                elif prev_vac >= threshold:
                    alerts.append(f"🚨 ID4101 FELL BELOW THRESHOLD: Vacancies dropped to {vac} (was {prev_vac})")
                elif prev_vac != vac:
                    alerts.append(f"🚨 ID4101 VACANCY UPDATE: Vacancies changed to {vac} (was {prev_vac})")
                    
        # Check CE5010
        elif cno == "CE5010":
            threshold = 10
            if vac < threshold:
                if prev_vac is None:
                    alerts.append(f"🚨 CE5010 CRITICAL: Vacancies are {vac} (under threshold of {threshold}!)")
                elif prev_vac >= threshold:
                    alerts.append(f"🚨 CE5010 FELL BELOW THRESHOLD: Vacancies dropped to {vac} (was {prev_vac})")
                elif prev_vac != vac:
                    alerts.append(f"🚨 CE5010 VACANCY UPDATE: Vacancies changed to {vac} (was {prev_vac})")
                    
    # 2. Process courses that have disappeared (vacancies dropped to 0)
    for state_key, prev_vac_str in prev_state.items():
        if state_key in current_keys:
            continue
            
        if "_" in state_key:
            cno, slot = state_key.split("_", 1)
        else:
            cno, slot = state_key, "Unknown"
            
        try:
            prev_vac = int(prev_vac_str)
        except ValueError:
            prev_vac = 0
            
        if prev_vac > 0:
            if cno.startswith("GN"):
                alerts.append(f"🔄 GN VACANCY CHANGE: {cno} (Slot: {slot}) has filled to 0 / disappeared (was {prev_vac})")
            elif cno == "ID4101" and prev_vac >= 20:
                alerts.append(f"🚨 ID4101 FELL BELOW THRESHOLD: Course filled to 0 / disappeared (was {prev_vac})")
            elif cno == "CE5010" and prev_vac >= 10:
                alerts.append(f"🚨 CE5010 FELL BELOW THRESHOLD: Course filled to 0 / disappeared (was {prev_vac})")
    
    return alerts


async def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
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
            save_state(gs_courses)

            if alerts:
                alert_text = "\n".join(alerts)
                subject = "IITM Course Alert: Slot Available!"
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
                send_email_alert(subject, body)
            else:
                print(f"[{now}] No changes detected. Tracked {len(gs_courses)} courses.")

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
