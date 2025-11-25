import os
import openpyxl
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func 
from jdatetime import date as jdate

# PDF Generation Imports
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from bidi.algorithm import get_display
import arabic_reshaper

from database.core import get_db
from database.models import User, Transaction, BotSetting, ReportArchive
from utils.jalali_helper import greg_to_jalali, jalali_to_greg, get_current_jalali
from utils.keyboards import get_back_button, get_admin_menu

# --- State Definitions ---
ADD_USER_ID, ADD_USER_UNIT, ADD_USER_NAME, ADD_USER_PHONE = range(4)
EDIT_SELECT_USER, EDIT_CHOOSE_FIELD, EDIT_GET_VALUE = range(4, 7)
EXP_AMOUNT, EXP_DATE, EXP_DESC, EXP_RECEIPT = range(7, 11)
SETTING_VAL = 11
MSG_SELECT_TYPE, MSG_GET_TEXT, MSG_GET_TARGET = range(12, 15)

# --- Helper Functions ---
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Safe back to menu function handling both callback queries and text messages"""
    context.user_data.clear()
    chat_id = update.effective_chat.id
    
    if update.callback_query:
        await update.callback_query.answer()
        if update.callback_query.message.photo or update.callback_query.message.document:
            await update.callback_query.message.delete()
            await context.bot.send_message(
                chat_id=chat_id, 
                text="👮‍♂️ **پنل مدیریت**\nدستور انجام شد.", 
                reply_markup=get_admin_menu(), 
                parse_mode="Markdown"
            )
        else:
            await update.callback_query.edit_message_text(
                text="👮‍♂️ **پنل مدیریت**\nدستور انجام شد.", 
                reply_markup=get_admin_menu(), 
                parse_mode="Markdown"
            )
    else:
        await context.bot.send_message(
            chat_id=chat_id, 
            text="👮‍♂️ **پنل مدیریت**\nدستور انجام شد.", 
            reply_markup=get_admin_menu(), 
            parse_mode="Markdown"
        )

def get_setting_value(db: Session, key: str, default: str = "-"):
    setting = db.query(BotSetting).filter(BotSetting.key == key).first()
    return setting.value if setting else default

def set_setting_value(db: Session, key: str, value: str):
    setting = db.query(BotSetting).filter(BotSetting.key == key).first()
    if not setting:
        setting = BotSetting(key=key, value=value)
        db.add(setting)
    else:
        setting.value = value
    db.commit()

def _get_rtl_text(text):
    """Reshape and apply BIDI for RTL text in ReportLab."""
    if not isinstance(text, str): text = str(text)
    reshaped_text = arabic_reshaper.reshape(text)
    return get_display(reshaped_text)

# ==========================================
# 1. USER MANAGEMENT
# ==========================================
async def admin_units(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query: await query.answer()
    
    db_gen = get_db(); db = next(db_gen)
    try:
        users = db.query(User).order_by(User.unit_number).all()
        msg = "🏘 **لیست ساکنین و واحدها:**\n\n"
        for u in users:
            bal_str = f"{u.balance:+,}"
            role = "👮‍♂️" if u.role == 'admin' else "👤"
            unit = u.unit_number or "?"
            name = u.full_name or "?"
            msg += f"{role} واحد {unit} | {name}\n📱 {u.phone_number or '-'}\n💰 تراز: {bal_str} | 🆔 `{u.telegram_id}`\n---\n"
            
        kb = [[InlineKeyboardButton("➕ ثبت ساکن", callback_data="adm_add_user_start"), InlineKeyboardButton("✏️ ویرایش", callback_data="adm_edit_user_start")], [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
        
        if query:
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        else:
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    finally: db.close()

# --- Add User ---
async def start_add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("➕ آیدی عددی تلگرام ساکن را وارد کنید:", reply_markup=get_back_button("adm_units"))
    return ADD_USER_ID

async def receive_new_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.text
    if not uid.isdigit(): await update.message.reply_text("❌ عدد وارد کنید."); return ADD_USER_ID
    context.user_data['new_uid'] = int(uid)
    await update.message.reply_text("🏠 شماره واحد:")
    return ADD_USER_UNIT

async def receive_new_user_unit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_unit'] = update.message.text
    await update.message.reply_text("👤 نام ساکن (یا -):")
    return ADD_USER_NAME

async def receive_new_user_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_name'] = update.message.text
    await update.message.reply_text("📱 شماره تماس (یا -):")
    return ADD_USER_PHONE

async def receive_new_user_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text
    name = context.user_data['new_name']
    if name == "-": name = "ناشناس"
    if phone == "-": phone = None
    
    db_gen = get_db(); db = next(db_gen)
    try:
        if db.query(User).filter(User.telegram_id == context.user_data['new_uid']).first():
            await update.message.reply_text("❌ کاربر تکراری.")
        else:
            u = User(telegram_id=context.user_data['new_uid'], unit_number=context.user_data['new_unit'], full_name=name, phone_number=phone, balance=0)
            db.add(u); db.commit()
            await update.message.reply_text("✅ ثبت شد.")
    finally: db.close()
    await admin_units(update, context)
    return ConversationHandler.END

# --- Edit User ---
async def start_edit_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("📝 آیدی عددی یا شماره واحد را وارد کنید:", reply_markup=get_back_button("adm_units"))
    return EDIT_SELECT_USER

async def select_user_to_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inp = update.message.text
    db_gen = get_db(); db = next(db_gen)
    
    if inp.isdigit() and len(inp) > 5: 
        user = db.query(User).filter(User.telegram_id == int(inp)).first()
    else: 
        user = db.query(User).filter(User.unit_number == inp).first()
    
    if not user:
        await update.message.reply_text("❌ یافت نشد.")
        db.close(); return EDIT_SELECT_USER
    
    context.user_data['edit_uid'] = user.id
    db.close()
    
    kb = [
        [InlineKeyboardButton("✏️ نام", callback_data="e_name"), InlineKeyboardButton("🏠 واحد", callback_data="e_unit")],
        [InlineKeyboardButton("📱 موبایل", callback_data="e_phone")],
        [InlineKeyboardButton("➕ افزایش موجودی", callback_data="e_inc_bal"), InlineKeyboardButton("➖ کاهش موجودی", callback_data="e_dec_bal")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="adm_units")]
    ]
    await update.message.reply_text(f"✅ ویرایش کاربر: **{user.full_name}**\n💰 تراز فعلی: {user.balance:,}", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return EDIT_CHOOSE_FIELD

async def choose_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    field = query.data
    context.user_data['edit_field'] = field
    
    if field in ["e_inc_bal", "e_dec_bal"]:
        action = "افزایش" if field == "e_inc_bal" else "کاهش"
        await query.edit_message_text(f"💰 مبلغ **{action}** اعتبار (تومان) را وارد کنید:", reply_markup=get_back_button("adm_units"), parse_mode="Markdown")
    else:
        map_name = {"e_name": "نام جدید", "e_unit": "شماره واحد جدید", "e_phone": "شماره موبایل جدید"}
        await query.edit_message_text(f"📝 {map_name.get(field, 'مقدار')} را وارد کنید:", reply_markup=get_back_button("adm_units"))
    return EDIT_GET_VALUE

async def save_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    field = context.user_data['edit_field']
    uid = context.user_data['edit_uid']
    
    db_gen = get_db(); db = next(db_gen)
    try:
        u = db.query(User).filter(User.id == uid).first()
        if not u: return ConversationHandler.END
        
        if field in ["e_inc_bal", "e_dec_bal"]:
            if not val.isdigit():
                await update.message.reply_text("❌ فقط عدد وارد کنید.")
                return EDIT_GET_VALUE
            
            amount = int(val)
            ttype = 'payment' if field == 'e_inc_bal' else 'charge'
            desc = "افزایش دستی توسط مدیر" if field == 'e_inc_bal' else "کاهش دستی توسط مدیر"
            
            t = Transaction(user_id=u.id, type=ttype, amount=amount, description=desc, status='approved', date=datetime.now())
            db.add(t)
            
            if field == 'e_inc_bal':
                u.balance += amount
                msg = f"✅ {amount:,} تومان به حساب اضافه شد.\n💰 تراز جدید: {u.balance:,}"
            else:
                u.balance -= amount
                msg = f"✅ {amount:,} تومان از حساب کسر شد.\n💰 تراز جدید: {u.balance:,}"
            
        else:
            if field == "e_name": u.full_name = val
            elif field == "e_unit": u.unit_number = val
            elif field == "e_phone": u.phone_number = val
            msg = "✅ اطلاعات با موفقیت ویرایش شد."
            
        db.commit()
        await update.message.reply_text(msg)
    finally: db.close()
    
    await admin_units(update, context)
    return ConversationHandler.END

# ==========================================
# 2. EXPENSES
# ==========================================
async def start_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("💸 مبلغ هزینه (تومان):", reply_markup=get_back_button("main_menu"))
    return EXP_AMOUNT

async def receive_exp_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text.isdigit(): return EXP_AMOUNT
    context.user_data['amt'] = int(update.message.text)
    await update.message.reply_text(f"📅 تاریخ (مثلا {get_current_jalali()}):")
    return EXP_DATE

async def receive_exp_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = update.message.text
    if d.strip() == "امروز": d = get_current_jalali()
    try: context.user_data['date'] = jalali_to_greg(d)
    except: await update.message.reply_text("❌ فرمت غلط."); return EXP_DATE
    await update.message.reply_text("📝 توضیحات:")
    return EXP_DESC

async def receive_exp_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['desc'] = update.message.text
    await update.message.reply_text("📸 عکس رسید (یا /skip):")
    return EXP_RECEIPT

async def receive_exp_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file = await update.message.photo[-1].get_file()
    os.makedirs("media/expenses", exist_ok=True)
    filename = f"media/expenses/exp_{int(datetime.now().timestamp())}.jpg"
    await photo_file.download_to_drive(filename)
    await save_expense_final(update, context, filename)
    return ConversationHandler.END

async def skip_exp_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_expense_final(update, context, None)
    return ConversationHandler.END

async def save_expense_final(update, context, filename):
    db_gen = get_db(); db = next(db_gen)
    try:
        t = Transaction(type='expense', amount=context.user_data['amt'], date=context.user_data['date'], description=context.user_data['desc'], receipt_image=filename, status='approved')
        db.add(t); db.commit()
        await update.message.reply_text("✅ هزینه ثبت شد.")
    finally: db.close()
    await back_to_menu(update, context)
    return ConversationHandler.END

# ==========================================
# 3. REQUESTS
# ==========================================
async def admin_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    db_gen = get_db(); db = next(db_gen)
    try:
        reqs = db.query(Transaction).options(joinedload(Transaction.user)).filter(Transaction.status == 'pending').order_by(Transaction.date.desc()).all()
        if not reqs: 
            await query.edit_message_text("✅ هیچ درخواستی برای تایید وجود ندارد.", reply_markup=get_back_button("main_menu"))
            return
            
        kb = []
        for r in reqs: 
            kb.append([InlineKeyboardButton(f"💰 {r.amount:,} | {r.user.full_name}", callback_data=f"adm_decide_{r.id}")])
        kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
        await query.edit_message_text("📥 درخواست‌های در انتظار تایید:", reply_markup=InlineKeyboardMarkup(kb))
    finally: db.close()

async def request_decision_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    tid = int(query.data.split("_")[2])
    db_gen = get_db(); db = next(db_gen)
    try:
        t = db.query(Transaction).options(joinedload(Transaction.user)).filter(Transaction.id == tid).first()
        if not t: await query.edit_message_text("❌ یافت نشد."); return
        msg = f"👤 کاربر: {t.user.full_name}\n💰 مبلغ: {t.amount:,}\n📅 تاریخ: {greg_to_jalali(t.date)}\n📝 توضیحات: {t.description or '-'}"
        kb = [[InlineKeyboardButton("✅ تایید", callback_data=f"adm_approve_{tid}"), InlineKeyboardButton("❌ رد", callback_data=f"adm_reject_{tid}")], [InlineKeyboardButton("🔙 بازگشت", callback_data="adm_requests")]]
        
        await query.message.delete()
        if t.receipt_image: 
            await context.bot.send_photo(query.message.chat_id, open(t.receipt_image, 'rb'), caption=msg, reply_markup=InlineKeyboardMarkup(kb))
        else: 
            await context.bot.send_message(query.message.chat_id, msg, reply_markup=InlineKeyboardMarkup(kb))
    finally: db.close()

async def perform_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    act, tid = query.data.split("_")[1], int(query.data.split("_")[2])
    db_gen = get_db(); db = next(db_gen)
    try:
        t = db.query(Transaction).options(joinedload(Transaction.user)).filter(Transaction.id == tid).first()
        if t and t.status == 'pending':
            if act == "approve":
                t.status = "approved"; t.user.balance += t.amount
                try: await context.bot.send_message(t.user.telegram_id, f"✅ واریزی شما به مبلغ {t.amount:,} تومان تایید شد.")
                except: pass
                res = "✅ تایید شد."
            else:
                t.status = "rejected"
                try: await context.bot.send_message(t.user.telegram_id, "❌ متاسفانه واریزی شما رد شد.")
                except: pass
                res = "❌ رد شد."
            db.commit()
            await query.message.delete()
            await context.bot.send_message(query.message.chat_id, res)
    finally: db.close()
    await admin_requests(update, context)

# ==========================================
# 4. SETTINGS
# ==========================================
async def admin_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    db_gen = get_db(); db = next(db_gen)
    try:
        card = get_setting_value(db, "card_number", "-")
        charge = get_setting_value(db, "monthly_charge", "0")
        due = get_setting_value(db, "charge_due_day", "1")
        init_val = db.query(func.sum(Transaction.amount)).filter(Transaction.type == 'initial').scalar() or 0
        
        msg = f"⚙️ **تنظیمات**\n💳 کارت: `{card}`\n💰 شارژ: `{charge}`\n📅 سررسید: `{due}`\n💾 موجودی اولیه: `{init_val:,}`"
        kb = [[InlineKeyboardButton("کارت", callback_data="adm_set_card"), InlineKeyboardButton("شارژ", callback_data="adm_set_charge")], [InlineKeyboardButton("سررسید", callback_data="adm_set_due"), InlineKeyboardButton("موجودی اولیه", callback_data="adm_set_initial")], [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    finally: db.close()

async def start_edit_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    key_map = {"adm_set_card": "card_number", "adm_set_charge": "monthly_charge", "adm_set_due": "charge_due_day", "adm_set_initial": "initial_fund"}
    if query.data in key_map:
        context.user_data['set_key'] = key_map[query.data]
        txt = "💎 مبلغ موجودی اولیه:" if context.user_data['set_key'] == "initial_fund" else "مقدار جدید را وارد کنید:"
        await query.edit_message_text(txt, reply_markup=get_back_button("adm_settings"))
        return SETTING_VAL
    return ConversationHandler.END

async def save_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    key = context.user_data.get('set_key')
    db_gen = get_db(); db = next(db_gen)
    try:
        if key == "initial_fund":
            if val.isdigit():
                db.query(Transaction).filter(Transaction.type == 'initial').delete()
                db.add(Transaction(type='initial', amount=int(val), description="تنظیم موجودی اولیه", status='approved', date=datetime.now()))
                await update.message.reply_text(f"✅ موجودی اولیه: {int(val):,}")
            else: await update.message.reply_text("❌ عدد وارد کنید.")
        else:
            set_setting_value(db, key, val)
            await update.message.reply_text("✅ ذخیره شد.")
        db.commit()
    finally: db.close()
    await admin_settings(update, context)
    return ConversationHandler.END

# ==========================================
# 5. MESSAGING
# ==========================================
async def admin_message_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📢 همه", callback_data="msg_all"), InlineKeyboardButton("⚠️ بدهکاران", callback_data="msg_debt")], [InlineKeyboardButton("🏠 واحد خاص", callback_data="msg_unit")], [InlineKeyboardButton("🔙", callback_data="main_menu")]]
    await query.edit_message_text("📨 گیرنده:", reply_markup=InlineKeyboardMarkup(kb))
    return MSG_SELECT_TYPE

async def receive_msg_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data['m_type'] = query.data
    if query.data == "msg_unit":
        await query.edit_message_text("🔢 شماره واحد:", reply_markup=get_back_button("adm_message_menu"))
        return MSG_GET_TARGET
    await query.edit_message_text("📝 متن پیام:", reply_markup=get_back_button("adm_message_menu"))
    return MSG_GET_TEXT

async def receive_msg_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['m_target'] = update.message.text
    await update.message.reply_text("📝 متن پیام:")
    return MSG_GET_TEXT

async def send_message_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    mt = context.user_data['m_type']
    db_gen = get_db(); db = next(db_gen)
    users = []
    
    if mt == "msg_all": users = db.query(User).filter(User.role == 'resident').all()
    elif mt == "msg_debt": users = db.query(User).filter(User.balance < 0).all()
    elif mt == "msg_unit": users = db.query(User).filter(User.unit_number == context.user_data['m_target']).all()
    
    c = 0
    for u in users:
        try: await context.bot.send_message(u.telegram_id, f"🔔 **پیام مدیریت:**\n\n{txt}", parse_mode="Markdown"); c += 1
        except: pass
    db.close()
    
    await update.message.reply_text(f"✅ ارسال شد به {c} نفر.")
    await back_to_menu(update, context)
    return ConversationHandler.END

# ==========================================
# 6. REPORTS (EXCEL & PDF)
# ==========================================
async def admin_reports_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📊 اکسل", callback_data="adm_report_excel"), InlineKeyboardButton("📋 PDF ماهانه", callback_data="adm_report_pdf")], [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    await query.edit_message_text("🗂️ نوع گزارش:", reply_markup=InlineKeyboardMarkup(kb))

async def generate_excel_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.message.reply_text("⏳ تولید اکسل...")
    db_gen = get_db(); db = next(db_gen)
    try:
        wb = openpyxl.Workbook()
        ws = wb.active; ws.title = "ساکنین"
        ws.append(["ID", "نام", "واحد", "تلفن", "بدهی", "پرداختی", "تراز"])
        for u in db.query(User).filter(User.role == 'resident').all():
            c = db.query(func.sum(Transaction.amount)).filter(Transaction.user_id==u.id, Transaction.type=='charge').scalar() or 0
            p = db.query(func.sum(Transaction.amount)).filter(Transaction.user_id==u.id, Transaction.type=='payment', Transaction.status=='approved').scalar() or 0
            ws.append([u.telegram_id, u.full_name, u.unit_number, u.phone_number, c, p, u.balance])
        ws.auto_filter.ref = ws.dimensions

        ws2 = wb.create_sheet("تراکنش‌ها")
        ws2.append(["ID", "کاربر", "نوع", "مبلغ", "تاریخ", "توضیحات"])
        for t in db.query(Transaction).options(joinedload(Transaction.user)).all():
            un = t.user.full_name if t.user else "سیستم"
            ws2.append([t.id, un, t.type, t.amount, greg_to_jalali(t.date), t.description])
        ws2.auto_filter.ref = ws2.dimensions
        
        wb.save("report.xlsx")
        await context.bot.send_document(query.message.chat_id, open("report.xlsx", 'rb'), caption="📊 گزارش اکسل")
        os.remove("report.xlsx")
    finally: db.close()
    await back_to_menu(update, context)

async def generate_monthly_pdf_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.message.reply_text("⏳ در حال تولید گزارش PDF...")
    db_gen = get_db(); db = next(db_gen)
    try:
        try: 
            pdfmetrics.registerFont(TTFont('Vazir', 'Vazir.ttf'))
            FONT_NAME = 'Vazir'
        except: 
            FONT_NAME = 'Helvetica'
        
        today = jdate.today()
        month_start = jdate(today.year, today.month, 1).togregorian()
        
        # ✅ FIX: لیست دستی روزهای ماه برای جلوگیری از ارور days_in_month
        j_days_in_month = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
        days_count = j_days_in_month[today.month - 1]
        
        # چک کردن سال کبیسه برای اسفند
        if today.month == 12 and today.isleap():
            days_count = 30
            
        month_end = jdate(today.year, today.month, days_count).togregorian()
        
        # Calculate Opening Balance
        prev_pay = db.query(func.sum(Transaction.amount)).filter(Transaction.type=='payment', Transaction.status=='approved', Transaction.date < month_start).scalar() or 0
        prev_init = db.query(func.sum(Transaction.amount)).filter(Transaction.type=='initial', Transaction.date < month_start).scalar() or 0
        prev_exp = db.query(func.sum(Transaction.amount)).filter(Transaction.type=='expense', Transaction.date < month_start).scalar() or 0
        opening_bal = (prev_pay + prev_init) - prev_exp
        
        # Current Month Activity
        curr_pay = db.query(func.sum(Transaction.amount)).filter(Transaction.type=='payment', Transaction.status=='approved', Transaction.date >= month_start, Transaction.date <= month_end).scalar() or 0
        curr_exp = db.query(func.sum(Transaction.amount)).filter(Transaction.type=='expense', Transaction.date >= month_start, Transaction.date <= month_end).scalar() or 0
        closing_bal = opening_bal + curr_pay - curr_exp
        
        # PDF Setup
        pdf_filename = f"report_{today.strftime('%Y-%m-%d')}.pdf"
        doc = SimpleDocTemplate(pdf_filename, pagesize=A4, rightMargin=inch*0.5, leftMargin=inch*0.5, topMargin=inch*0.5, bottomMargin=inch*0.5)
        story = []
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle('RTL_TITLE', parent=styles['Normal'], fontName=FONT_NAME, fontSize=16, alignment=2, spaceAfter=15, textColor=colors.HexColor('#134252'))
        heading_style = ParagraphStyle('RTL_HEADING', parent=styles['Normal'], fontName=FONT_NAME, fontSize=13, alignment=2, spaceBefore=12, spaceAfter=8, textColor=colors.HexColor('#134252'))
        normal_style = ParagraphStyle('RTL_NORMAL', parent=styles['Normal'], fontName=FONT_NAME, fontSize=11, alignment=2)

        # Title
        story.append(Paragraph(_get_rtl_text(f"گزارش مالی ساختمان - {today.strftime('%Y/%m/%d')}"), title_style))
        
        # Section 1: Summary
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
        story.append(t1); story.append(Spacer(1, 0.2*inch))
        
        # Section 2: Residents
        story.append(Paragraph(_get_rtl_text("وضعیت مالی واحدها"), heading_style))
        res_data = [[_get_rtl_text("وضعیت"), _get_rtl_text("تراز (تومان)"), _get_rtl_text("واحد")]]
        residents = db.query(User).filter(User.role == 'resident').order_by(User.unit_number).all()
        for u in residents:
            status = "بدهکار" if u.balance < 0 else "بستانکار" if u.balance > 0 else "تسویه"
            res_data.append([_get_rtl_text(status), f"{u.balance:,}", _get_rtl_text(u.unit_number or "-")])
            
        t2 = Table(res_data, colWidths=[2*inch, 3*inch, 2*inch])
        t2.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#16a085')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
            ('FONTNAME', (0,0), (-1,-1), FONT_NAME),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.white])
        ]))
        story.append(t2); story.append(Spacer(1, 0.2*inch))

        # Section 3: Expenses
        story.append(Paragraph(_get_rtl_text("آخرین هزینه‌های ثبت شده"), heading_style))
        recent_expenses = db.query(Transaction).filter(Transaction.type=='expense', Transaction.date>=month_start, Transaction.date<=month_end).order_by(Transaction.date.desc()).all()
        if recent_expenses:
            exp_data = [[_get_rtl_text("شرح"), _get_rtl_text("مبلغ"), _get_rtl_text("تاریخ")]]
            for e in recent_expenses:
                exp_data.append([_get_rtl_text(e.description or "-"), f"{e.amount:,}", greg_to_jalali(e.date)])
            t3 = Table(exp_data, colWidths=[3.5*inch, 2*inch, 1.5*inch])
            t3.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#c0392b')),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
                ('FONTNAME', (0,0), (-1,-1), FONT_NAME),
                ('GRID', (0,0), (-1,-1), 1, colors.black),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.white])
            ]))
            story.append(t3)
        else:
            story.append(Paragraph(_get_rtl_text("هیچ هزینه‌ای در این ماه ثبت نشده است."), normal_style))

        doc.build(story)
        await context.bot.send_document(query.message.chat_id, open(pdf_filename, 'rb'), caption="📋 گزارش ماهانه")
        os.remove(pdf_filename)
        
    except Exception as e:
        await context.bot.send_message(query.message.chat_id, f"❌ خطا در تولید PDF: {e}")
    finally: db.close()
    
    await back_to_menu(update, context)

async def admin_balance_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    db_gen = get_db(); db = next(db_gen)
    try:
        pay = db.query(func.sum(Transaction.amount)).filter(Transaction.type == 'payment', Transaction.status == 'approved').scalar() or 0
        init = db.query(func.sum(Transaction.amount)).filter(Transaction.type == 'initial').scalar() or 0
        exp = db.query(func.sum(Transaction.amount)).filter(Transaction.type == 'expense').scalar() or 0
        net = (pay + init) - exp
        msg = f"💰 **صندوق**\n\n📥 دریافتی: {pay:,}\n💾 اولیه: {init:,}\n📤 هزینه: {exp:,}\n💎 **موجودی:** {net:,}"
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=get_back_button("main_menu"))
    finally: db.close()

async def admin_view_as_resident(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from utils.keyboards import get_resident_menu
    await update.callback_query.edit_message_text("نمای ساکن:", reply_markup=get_resident_menu())

# ==========================================
# 7. ARCHIVE REPORTS
# ==========================================
async def admin_archive_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show archived reports menu"""
    query = update.callback_query; await query.answer()
    db_gen = get_db(); db = next(db_gen)
    try:
        archives = db.query(ReportArchive).order_by(ReportArchive.jalali_month.desc()).all()
        if not archives:
            await query.edit_message_text("📁 گزارش‌های بایگانی شده‌ای وجود ندارد.", reply_markup=get_back_button("main_menu"))
            return
        
        kb = []
        for arch in archives:
            kb.append([InlineKeyboardButton(f"📅 {arch.jalali_month}", callback_data=f"arch_view_{arch.id}")])
        kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
        
        await query.edit_message_text("📁 **گزارش‌های بایگانی شده:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    finally: db.close()

async def view_archive_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View specific archived report"""
    query = update.callback_query; await query.answer()
    arch_id = int(query.data.split("_")[2])
    db_gen = get_db(); db = next(db_gen)
    try:
        arch = db.query(ReportArchive).filter(ReportArchive.id == arch_id).first()
        if not arch:
            await query.edit_message_text("❌ گزارش یافت نشد.")
            return
        
        kb = [
            [InlineKeyboardButton("📊 اکسل", callback_data=f"arch_dl_excel_{arch_id}"), InlineKeyboardButton("📋 PDF", callback_data=f"arch_dl_pdf_{arch_id}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="arch_reports")]
        ]
        await query.edit_message_text(f"📅 گزارش {arch.jalali_month}\n\nکدام فرمت را دانلود کنید؟", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    finally: db.close()

async def download_archive_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Download specific archive file"""
    query = update.callback_query; await query.answer()
    parts = query.data.split("_")
    file_type = parts[2]  # excel or pdf
    arch_id = int(parts[3])
    
    db_gen = get_db(); db = next(db_gen)
    try:
        arch = db.query(ReportArchive).filter(ReportArchive.id == arch_id).first()
        if not arch:
            await query.message.reply_text("❌ گزارش یافت نشد.")
            return
        
        if file_type == "excel":
            file_path = arch.excel_file_path
            caption = f"📊 اکسل {arch.jalali_month}"
        else:
            file_path = arch.pdf_file_path
            caption = f"📋 PDF {arch.jalali_month}"
        
        if os.path.exists(file_path):
            await context.bot.send_document(query.message.chat_id, open(file_path, 'rb'), caption=caption)
        else:
            await query.message.reply_text("❌ فایل یافت نشد.")
    finally: db.close()

async def cancel_op(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query: await query.answer()
    await back_to_menu(update, context)
    return ConversationHandler.END
