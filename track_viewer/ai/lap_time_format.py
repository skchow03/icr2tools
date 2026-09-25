"""Display helpers for racing-line lap times."""


def format_lap_time(seconds: float) -> str:
    """Format a lap duration as M:SS.mmm, including correct minute rollover."""
    milliseconds = round(float(seconds) * 1000)
    sign = "-" if milliseconds < 0 else ""
    total_seconds, fraction = divmod(abs(milliseconds), 1000)
    minutes, whole_seconds = divmod(total_seconds, 60)
    return f"{sign}{minutes}:{whole_seconds:02d}.{fraction:03d}"
