from pathlib import Path

from common.report_pdf import render_weekly_pdf


report = {
    "start_date": "2026-10-19",
    "end_date": "2026-10-25",
    "total_duration_sec": 7_860,
    "blocked_count": 2,
    "daily": [
        {"date": "2026-10-19", "duration_sec": 3_960},
        {"date": "2026-10-20", "duration_sec": 0},
        {"date": "2026-10-21", "duration_sec": 1_200},
        {"date": "2026-10-22", "duration_sec": 900},
        {"date": "2026-10-23", "duration_sec": 1_800},
        {"date": "2026-10-24", "duration_sec": 0},
        {"date": "2026-10-25", "duration_sec": 0},
    ],
    "top_apps": [
        {"subject": "chrome.exe", "duration_sec": 3_900, "starts": 4},
        {"subject": "mspaint.exe", "duration_sec": 1_620, "starts": 2},
        {"subject": "Ứng dụng học tập.exe", "duration_sec": 1_200, "starts": 1},
    ],
    "top_domains": [
        {"subject": "example.edu", "queries": 18},
        {"subject": "wikipedia.org", "queries": 9},
    ],
    "requests": [],
}

output = Path("output/pdf/dashboard-parent-weekly-report-preview.pdf")
output.write_bytes(render_weekly_pdf(report, "Bé An"))
print(output.resolve())
