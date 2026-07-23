# IITM Course Monitor (Cloud Edition)

This is a Python script that runs automatically every 5 minutes in a **GitHub Action** to scan the IIT Madras student workflow portal for General Studies (GN) electives and tracked courses (`ID4101`, `CE5010`), and notify you when slot numbers change or fall below critical limits.

---

## Setup Instructions

### Step 1: Create a Private GitHub Repository
1. Log in to [GitHub](https://github.com/) (using your account `vahid-kanna`).
2. Click **New Repository**.
3. Name the repository: `iitm-course-monitor`.
4. **⚠️ IMPORTANT:** Set the repository visibility to **Private** (do NOT choose Public to keep your logging/credits confidential).
5. Leave "Add a README" unchecked, and click **Create repository**.

### Step 2: Configure Actions Secrets
Since you do not want to hardcode your passwords or smail keys in the repo, add them as **Actions Secrets**:
1. In your GitHub repository page, go to **Settings** (top tabs) -> **Secrets and variables** (left sidebar) -> **Actions**.
2. Click **New repository secret** (green button).
3. Add the following three secrets:
   * **Name:** `IITM_LDAP_USER` | **Value:** `ce23b115`
   * **Name:** `IITM_LDAP_PASS` | **Value:** `Vahid@@@2005`
   * **Name:** `SMAIL_PASS` | **Value:** `shcy dsbp imof eywa` *(Your Gmail/Smail app password)*

### Step 3: Initialize Git and Push the Repository
Open your computer's terminal (or Git Bash) and run the following commands to upload everything:

```bash
# Navigate to the cloud package folder
cd "/c/Users/vahid/iitm_course_monitor_gh"

# Initialize local git repository
git init

# Add all files
git add .
git commit -m "Initial commit for IITM course monitor"

# Link to your GitHub profile and push
git branch -M main
git remote add origin https://github.com/vahid-kanna/iitm-course-monitor.git

# Push code (GitHub will prompt you to login or enter credentials)
git push -u origin main
```

---

## How It Works
* **GitHub Scheduler:** Every 5 minutes, GitHub runs the job. It restores the previous state cached file (`last_gs_state.json`), downloads playwright, logs into the portal via the proxy, matches current values, and updates.
* **SMTP Delivery:** Emails are directly triggered from GitHub Actions using Python's built-in `smtplib` library linking to your `smtp.gmail.com` smail account securely. No third-party APIs used.
* **Manual Checks:** You can also run the monitor manually by going to your repository page -> **Actions** -> **IITM Course Monitor** -> click **Run workflow**!
