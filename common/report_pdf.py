"""Printable Vietnamese weekly activity report."""

from __future__ import annotations

from datetime import date, datetime
from html import escape
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from common.activity_reports import REPORT_ZONE
from common.report_charts import render_report_chart

GREEN = colors.HexColor("#226B54")
PALE = colors.HexColor("#EAF3ED")
TEXT = colors.HexColor("#173B38")


def _register_fonts() -> None:
    if "OGKDejaVu" in pdfmetrics.getRegisteredFontNames():
        return
    roots = (
        Path("C:/Windows/Fonts"),
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/local/share/fonts"),
    )
    pairs = [(root / "DejaVuSans.ttf", root / "DejaVuSans-Bold.ttf") for root in roots]
    # Standard Windows installations provide Arial, but usually not DejaVu.
    pairs.append((Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")))
    for regular, bold in pairs:
        if regular.is_file() and bold.is_file():
            pdfmetrics.registerFont(TTFont("OGKDejaVu", str(regular)))
            pdfmetrics.registerFont(TTFont("OGKDejaVu-Bold", str(bold)))
            return
    raise RuntimeError("DejaVu Sans or Windows Arial is required to export Vietnamese PDF reports")


def _duration(seconds: float) -> str:
    minutes = max(0, round(seconds)) // 60
    hours, minutes = divmod(minutes, 60)
    return f"{hours} giờ {minutes:02d} phút" if hours else f"{minutes} phút"


def _date(value: str) -> str:
    return date.fromisoformat(value).strftime("%d/%m/%Y")


def _weekday_date(value: str) -> str:
    day = date.fromisoformat(value)
    weekdays = ("Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật")
    return f"{weekdays[day.weekday()]}, {day:%d/%m/%Y}"


def _friendly_app_name(value: str) -> str:
    filename = value.strip()
    known_apps = {
        "chrome.exe": "Google Chrome",
        "msedge.exe": "Microsoft Edge",
        "firefox.exe": "Mozilla Firefox",
        "winword.exe": "Microsoft Word",
        "excel.exe": "Microsoft Excel",
        "powerpnt.exe": "Microsoft PowerPoint",
        "zalo.exe": "Zalo",
        "discord.exe": "Discord",
        "spotify.exe": "Spotify",
        "paint.exe": "Paint",
        "mspaint.exe": "Paint",
    }
    if filename.casefold() in known_apps:
        return known_apps[filename.casefold()]
    return filename[:-4] if filename.casefold().endswith(".exe") else filename


def render_weekly_pdf(report: dict, child_name: str) -> bytes:
    """Render one child's Monday-Sunday activity as a downloadable PDF."""
    _register_fonts()
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=42,
        rightMargin=42,
        topMargin=42,
        bottomMargin=42,
        title="Báo cáo tuần - OpenGuard Kids",
        author="OpenGuard Kids",
    )
    normal = ParagraphStyle("normal", fontName="OGKDejaVu", fontSize=9, leading=14, textColor=TEXT)
    heading = ParagraphStyle(
        "heading",
        parent=normal,
        fontName="OGKDejaVu-Bold",
        fontSize=13,
        leading=18,
        spaceBefore=15,
        spaceAfter=7,
    )
    title = ParagraphStyle("title", parent=heading, fontSize=19, leading=26, spaceBefore=0)
    small = ParagraphStyle("small", parent=normal, fontSize=8, leading=12)

    def p(value, style=normal):
        return Paragraph(escape(str(value)), style)

    def table(headers, rows, widths):
        cells = [[p(value, small) for value in headers]]
        cells.extend([[p(value, small) for value in row] for row in rows])
        result = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
        result.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), PALE),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C9DBCF")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return result

    story = [
        p("Báo cáo hoạt động tuần", title),
        p(f"Hồ sơ: {child_name}"),
        p(
            f"Từ {_date(report['start_date'])} đến {_date(report['end_date'])} · Giờ Việt Nam (UTC+7)"
        ),
        Spacer(1, 10),
        table(
            ("Tổng thời gian dùng máy", "Số lần bị chặn"),
            [(_duration(report["total_duration_sec"]), str(report["blocked_count"]))],
            [255, 255],
        ),
        p("Thời gian sử dụng từng ngày", heading),
        p(
            "Mỗi cột tương ứng với một ngày. Nhãn phía trên cột là tổng thời gian trẻ đã dùng máy.",
            small,
        ),
        Spacer(1, 5),
    ]
    chart = BytesIO(render_report_chart(report["daily"], "daily"))
    story.append(Image(chart, width=510, height=198))
    story.append(Spacer(1, 8))
    story.append(
        table(
            ("Ngày", "Thời gian sử dụng"),
            [
                (_weekday_date(item["date"]), _duration(item["duration_sec"]))
                for item in report["daily"]
            ],
            [255, 255],
        )
    )
    story.append(
        KeepTogether(
            [
                p("Ứng dụng được sử dụng nhiều", heading),
                p(
                    "Danh sách chỉ hiển thị ứng dụng người dùng thường nhận biết; các tiến trình nền phổ biến đã được loại bỏ. Nhiều ứng dụng có thể chạy cùng lúc nên thời gian có thể chồng lấp.",
                    small,
                ),
                Spacer(1, 5),
                table(
                    ("Ứng dụng", "Thời gian hoạt động"),
                    [
                        (_friendly_app_name(item["subject"]), _duration(item["duration_sec"]))
                        for item in report["top_apps"]
                    ]
                    or [("Chưa có dữ liệu", "")],
                    [350, 160],
                ),
            ]
        )
    )
    story.append(
        KeepTogether(
            [
                p("Tên miền xuất hiện nhiều", heading),
                p(
                    "Đây là số lần thiết bị tra cứu tên miền, không phải số lần trẻ mở trang web.",
                    small,
                ),
                Spacer(1, 5),
                table(
                    ("Tên miền", "Số lượt ghi nhận"),
                    [(item["subject"], str(item["queries"])) for item in report["top_domains"]]
                    or [("Chưa có dữ liệu", "")],
                    [350, 160],
                ),
            ]
        )
    )
    statuses = {"pending": "Đang chờ", "approved": "Được đồng ý", "rejected": "Bị từ chối"}
    story.append(
        KeepTogether(
            [
                p("Yêu cầu xin thêm thời gian", heading),
                table(
                    ("Thời điểm (UTC+7)", "Số phút", "Trạng thái"),
                    [
                        (
                            datetime.fromtimestamp(item["created_at"], REPORT_ZONE).strftime(
                                "%d/%m/%Y %H:%M"
                            ),
                            str(item["minutes"]),
                            statuses.get(item["status"], item["status"]),
                        )
                        for item in report["requests"]
                    ]
                    or [("Không có yêu cầu", "", "")],
                    [225, 95, 190],
                ),
            ]
        )
    )
    story.append(Spacer(1, 13))
    story.append(
        p(
            "Dữ liệu từ các thiết bị đã đồng bộ. Thời gian dùng máy không tính lúc khóa máy, "
            "khi trẻ không thao tác quá 5 phút hoặc khi ứng dụng OpenGuard Kids không hoạt động.",
            small,
        )
    )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(GREEN)
        canvas.line(42, 31, A4[0] - 42, 31)
        canvas.setFont("OGKDejaVu", 8)
        canvas.setFillColor(TEXT)
        canvas.drawString(42, 19, "OpenGuard Kids")
        canvas.drawRightString(A4[0] - 42, 19, f"Trang {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
