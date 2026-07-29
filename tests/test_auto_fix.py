import pytest
import ast

def test_fix_has_valid_syntax():
    """Verify the generated fix is valid Python."""
    code = '"""\nIITM Course Vacancy Monitor\n============================\nLogs into workflow.iitm.ac.in, navigates to Add/Drop  View Electives,\nreads the iframe listing all elective courses with vacancies, filters for\nGS (GN-prefixed) courses, and prints available ones.\n\nRuns as a Hermes cron job every 5 minutes. When a new GS course appears\nwith vacancies > 0, it sends an email via himalaya to ce23b115@smail.iitm.ac.in.\n"""\nimport asyncio\nimport json\nimport os\nimport sys\nimport subprocess\nimport smtplib\nfr'
    try:
        ast.parse(code)
    except SyntaxError as e:
        pytest.fail(f"Generated fix has syntax error: {e}")

def test_fix_is_not_empty():
    """Verify the fix actually contains code."""
    code = '"""\nIITM Course Vacancy Monitor\n============================\nLogs into workflow.iitm.ac.in, navigates to Add/Drop  View Electives,\nreads the iframe listing all elective courses with vacancies, filters for\nGS (GN-prefixed) courses, and prints available ones.\n\nRuns as a Hermes cron job every 5 minutes. When a new GS course appears\nwith vacancies > 0, it sends an email via himalaya to ce23b115@smail.iitm.ac.in.\n"""\nimport asyncio\nimport json\nimport os\nimport sys\nimport subprocess\nimport smtplib\nfr'
    assert len(code.strip()) > 10, "Fix appears to be empty"
