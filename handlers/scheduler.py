import os
from datetime import datetime
from jdatetime import date as jdate
from sqlalchemy import func
from telegram.ext import ContextTypes
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from bidi.algorithm import get_display
import arabic_reshaper
import openpyxl

from database.core import get_db
from database.models import User, Transaction, ReportArchive
from utils.jalali_helper import greg_to_jalali

def _get_rtl_text(text):
    """RTL text for PDF"""
    if not isinstance(text, str): text = str(text)
    return get_display(arabic_reshaper.reshape(text))

async def generate_last_month_report(context: ContextTypes.DEFAULT_TYPE):
    """Auto-generate report for the last month and save to archive"""
    db_gen = get_db(); db = next(db_gen)
    try:
        today = jdate.today()
        # Calculate last month
        if today.month == 1:
            last_month = jdate(today.year - 1, 12, 1)
        else:
            last_month = jdate(today.year, today.month - 1, 1)
        jalali_month_str = last_month.strftime('%Y/%m')

        # Check if already archived
        existing = db.query(ReportArchive).filter(ReportArchive.jalali_month == jalali_month_str).first()
        if existing:
            return  # Already archived

        # Date range for last month
        month_start = last_month.togregorian()

        # ✅ لیست دستی تعداد روزهای ماه جلالی
        j_days_in_month = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
        days_count = j_days_in_month[last_month.month - 1]
        if last_month.month == 12 and last_month.isleap():
            days_count = 30
        month_end = jdate(last_month.year, last_month.month, days_count).togregorian()

        # === Generate EXCEL ===
        os.makedirs("reports/archive", exist_ok=True)
        excel_filename = f"reports/archive/report_excel_{jalali_month_str.replace('/', '-')}.xlsx"

        wb = openpyxl.Workbook()
        ws = wb.active; ws.title = "ساکنین"
        ws.append(["ID", "نام", "واحد", "تلفن", "بدهی", "پرداختی", "تراز"])
        for u in db.query(User).filter(User.role == 'resident').all():
            c = db.query(func.sum(Transaction.amount)).filter(Transaction.user_id==u.id, Transaction.type=='charge').scalar() or 0
            p = db.query(func.sum(Transaction.amount)).filter(Transaction.user_id==u.id, Transaction.type=='payment', Transaction.status=='approved').scalar() or 0
            ws.append([u.telegram_id, u.full_name, u.unit_number, u.phone_number, c, p, u.balance])

        ws2 = wb.create_sheet("تراکنش‌ها")
        ws2.append(["ID", "کاربر", "نوع", "مبلغ", "تاریخ", "توضیحات"])
        for t in db.query(Transaction).all():
            un = t.user.full_name if t.user else "سیستم"
            ws2.append([t.id, un, t.type, t.amount, greg_to_jalali(t.date), t.description])

        wb.save(excel_filename)

        # === Generate PDF ===
        pdf_filename = f"reports/archive/report_pdf_{jalali_month_str.replace('/', '-')}.pdf"
        try:
            pdfmetrics.registerFont(TTFont('Vazir', 'Vazir.ttf'))
            FONT_NAME = 'Vazir'
        except:
            FONT_NAME = 'Helvetica'

        # Calculations
        prev_pay = db.query(func.sum(Transaction.amount)).filter(Transaction.type=='payment', Transaction.status=='approved', Transaction.date < month_start).scalar() or 0
        prev_init = db.query(func.sum(Transaction.amount)).filter(Transaction.type=='initial', Transaction.date < month_start).scalar() or 0
        prev_exp = db.query(func.sum(Transaction.amount)).filter(Transaction.type=='expense', Transaction.date < month_start).scalar() or 0
        opening_bal = (prev_pay + prev_init) - prev_exp

        curr_pay = db.query(func.sum(Transaction.amount)).filter(Transaction.type=='payment', Transaction.status=='approved', Transaction.date >= month_start, Transaction.date <= month_end).scalar() or 0
        curr_exp = db.query(func.sum(Transaction.amount)).filter(Transaction.type=='expense', Transaction.date >= month_start, Transaction.date <= month_end).scalar() or 0
        closing_bal = opening_bal + curr_pay - curr_exp

        doc = SimpleDocTemplate(pdf_filename, pagesize=A4, rightMargin=inch*0.5, leftMargin=inch*0.5, topMargin=inch*0.5, bottomMargin=inch*0.5)
        story = []
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle('RTL_TITLE', parent=styles['Normal'], fontName=FONT_NAME, fontSize=16, alignment=2, spaceAfter=15, textColor=colors.HexColor('#134252'))
        heading_style = ParagraphStyle('RTL_HEADING', parent=styles['Normal'], fontName=FONT_NAME, fontSize=13, alignment=2, spaceBefore=12, spaceAfter=8, textColor=colors.HexColor('#134252'))

        story.append(Paragraph(_get_rtl_text(f"گزارش مالی ساختمان - {jalali_month_str}"), title_style))

        # Summary Table
        story.append(Paragraph(_get_rtl_text("خلاصه وضعیت صندوق"), heading_style))
        summary_data = [
            [_get_rtl_text("مبلغ (تومان)"), _get_rtl_text("شرح")],
            [f"{opening_bal:,}", _get_rtl_text("موجودی اول دوره")],
            [f"{curr_pay:,}", _get_rtl_text("واریزی‌های این ماه (+)")],
            [f"{curr_exp:,}", _get_rtl_text("هزینه‌های این ماه (-)")],
            [f"{closing_bal:,}", _get_rtl_text("موجودی پایان دوره")]
        ]
        t1 = Table(summary_data, colWidths=[2.5*inch, 4.5*inch])
        t1.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
            ('FONTNAME', (0,0), (-1,-1), FONT_NAME),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.white])
        ]))
        story.append(t1)

        doc.build(story)

        # === Save to database ===
        archive = ReportArchive(
            jalali_month=jalali_month_str,
            gregorian_month=month_start.strftime('%Y/%m'),
            excel_file_path=excel_filename,
            pdf_file_path=pdf_filename,
            created_at=datetime.now()
        )
        db.add(archive)
        db.commit()

        print(f"✅ گزارش {jalali_month_str} ذخیره شد.")

    except Exception as e:
        print(f"❌ خطا در تولید گزارش خودکار: {e}")
    finally:
        db.close()
