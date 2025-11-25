import jdatetime
from datetime import datetime

def greg_to_jalali(greg_date_time: datetime, format_str="%Y/%m/%d") -> str:
    """
    Converts a Gregorian datetime object to a Jalali date string.
    Example: datetime(2023, 3, 21) -> "1402/01/01"
    """
    if not greg_date_time:
        return "-"
    
    jalali_date = jdatetime.datetime.fromgregorian(datetime=greg_date_time)
    return jalali_date.strftime(format_str)

def jalali_to_greg(jalali_str: str) -> datetime:
    """
    Converts a Jalali date string (e.g., "1402/01/01") to a Gregorian datetime object.
    Raises ValueError if format is invalid.
    """
    try:
        # Expecting format: YYYY/MM/DD
        j_year, j_month, j_day = map(int, jalali_str.split('/'))
        greg_date = jdatetime.date(j_year, j_month, j_day).togregorian()
        
        # Return as datetime (midnight)
        return datetime(greg_date.year, greg_date.month, greg_date.day)
    except Exception as e:
        raise ValueError("فرمت تاریخ اشتباه است. لطفا به صورت 1402/01/01 وارد کنید.")

def get_current_jalali() -> str:
    """Returns current date in Jalali string format."""
    return jdatetime.datetime.now().strftime("%Y/%m/%d")
