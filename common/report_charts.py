"""Small, deterministic PNG charts for parent activity reports."""

from datetime import date
from io import BytesIO
from math import ceil

from PIL import Image, ImageDraw, ImageFont

WIDTH = 800
HEIGHT = 310
PLOT_LEFT = 72
PLOT_RIGHT = 780
PLOT_TOP = 18
PLOT_BOTTOM = 220
BACKGROUND = "#F3F8F5"
BAR = "#226B54"
GRID = "#B8CCC1"
TEXT = "#173B38"


def rolling_week_columns(daily):
    """Group 56 chronological calendar days into eight consecutive seven-day columns."""
    if len(daily) != 56:
        raise ValueError("Weekly chart requires exactly 56 daily rows")
    return [
        {
            "week_start": daily[index]["date"],
            "week_end": daily[index + 6]["date"],
            "duration_sec": sum(row["duration_sec"] for row in daily[index : index + 7]),
        }
        for index in range(0, 56, 7)
    ]


def _hour_step(maximum_seconds):
    target = max(1, maximum_seconds) / 3600 / 4
    for step in (0.25, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000):
        if step >= target:
            return step
    return ceil(target / 1000) * 1000


def _hour_label(hours):
    return f"{hours:g}".replace(".", ",")


def _duration_label(seconds):
    minutes = max(0, round(seconds)) // 60
    hours, minutes = divmod(minutes, 60)
    return f"{hours}g {minutes:02d}p" if hours else f"{minutes}p"


def _daily_axis_label(value):
    day = date.fromisoformat(value)
    weekdays = ("T2", "T3", "T4", "T5", "T6", "T7", "CN")
    return weekdays[day.weekday()], day.strftime("%d/%m")


def _font(size):
    for name in ("C:/Windows/Fonts/segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_report_chart(items, kind):
    """Render one day/week column per bucket or ten horizontal application bars."""
    if kind not in {"daily", "weekly", "apps"}:
        raise ValueError("Unknown chart kind")
    width = 440 if kind == "apps" else WIDTH
    height = max(96, 36 + 41 * min(len(items), 10)) if kind == "apps" else HEIGHT
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    if kind == "apps":
        maximum = max((max(0, row["duration_sec"]) for row in items), default=1) or 1
        if not items:
            draw.text((20, 18), "Chưa có hoạt động ứng dụng.", fill=TEXT, font=_font(18))
        for index, row in enumerate(items[:10]):
            y = 20 + index * 41
            name = row["subject"]
            while draw.textlength(name, font=_font(15)) > 280 and len(name) > 4:
                name = name[:-2] + "…"
            duration = max(0, row["duration_sec"])
            duration_label = (
                f"{duration // 3600}g {(duration % 3600) // 60}p"
                if duration >= 3600
                else f"{duration // 60}p {duration % 60}s"
            )
            draw.text((20, y), name, fill=TEXT, font=_font(15))
            draw.text((345, y), duration_label, fill=TEXT, font=_font(15))
            draw.rectangle((20, y + 23, 420, y + 28), fill=GRID)
            if duration:
                draw.rectangle((20, y + 23, 20 + round(400 * duration / maximum), y + 28), fill=BAR)
    else:
        maximum = max((max(0, row["duration_sec"]) for row in items), default=1) or 1
        hour_step = _hour_step(maximum)
        tick_count = max(1, ceil(maximum / 3600 / hour_step))
        axis_max = tick_count * hour_step * 3600
        draw.text((8, 3), "Giờ", fill=TEXT, font=_font(14))
        for tick in range(tick_count + 1):
            y = round(PLOT_BOTTOM - (PLOT_BOTTOM - PLOT_TOP) * tick / tick_count)
            hours = tick * hour_step
            label = _hour_label(hours)
            label_width = draw.textlength(label, font=_font(13))
            draw.text((PLOT_LEFT - 12 - label_width, y - 8), label, fill=TEXT, font=_font(13))
            draw.line((PLOT_LEFT, y, PLOT_RIGHT, y), fill=GRID, width=2 if tick == 0 else 1)
        count = max(1, len(items))
        slot = (PLOT_RIGHT - PLOT_LEFT) / count
        bar_width = max(3, min(22, round(slot * 0.60)))
        for index, row in enumerate(items):
            value = max(0, row["duration_sec"])
            x = PLOT_LEFT + (index + 0.5) * slot
            if value:
                top = PLOT_BOTTOM - max(2, round((PLOT_BOTTOM - PLOT_TOP) * value / axis_max))
                draw.rounded_rectangle(
                    (round(x - bar_width / 2), top, round(x + bar_width / 2), PLOT_BOTTOM),
                    radius=min(3, bar_width // 3),
                    fill=BAR,
                )
                value_label = _duration_label(value)
                value_width = draw.textlength(value_label, font=_font(12))
                draw.text(
                    (round(x - value_width / 2), max(PLOT_TOP, top - 18)),
                    value_label,
                    fill=TEXT,
                    font=_font(12),
                )
            if kind == "daily":
                weekday, calendar_day = _daily_axis_label(row["date"])
                for line, y, font_size in (
                    (weekday, PLOT_BOTTOM + 8, 13),
                    (calendar_day, PLOT_BOTTOM + 27, 12),
                ):
                    font = _font(font_size)
                    label_width = draw.textlength(line, font=font)
                    draw.text((round(x - label_width / 2), y), line, fill=TEXT, font=font)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
