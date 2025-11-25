import os
import openpyxl
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func 
from database.core import get_db
from database.models import User, Transaction, BotSetting
from utils.jalali_helper import greg_to_jalali, jalali_to_greg, get_current_jalali
from utils.keyboards import get_back_button, get_admin_menu

# --- State Definitions ---
# Add User
ADD_USER_ID, ADD_USER_UNIT, ADD_USER_NAME, ADD_USER_PHONE = range(4)
# Edit User
EDIT_SELECT_USER, EDIT_CHOOSE_FIELD, EDIT_GET_VALUE = range(4, 7)
# Expenses
EXP_AMOUNT, EXP_DATE, EXP_DESC, EXP_RECEIPT = range(7, 11)
# Settings
SETTING_VAL = 11
# Messaging
MSG_SELECT_TYPE, MSG_GET_TEXT, MSG_GET_TARGET = range(12, 15)


# --- Helper Functions ---
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Clear context to prevent state conflict
    context.user_data.clear()
    chat_id = update.effective_chat.id
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


# ==========================================
# 1. USER MANAGEMENT
# ==========================================
async def admin_units(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db_gen = get_db(); db = next(db_gen)
    try:
        users = db.query(User).all()
        msg = "🏘 **لیست ساکنین و واحدها:**\n\n"
        for u in users:
            bal_str = f"+{u.balance:,}" if u.balance > 0 else f"{u.balance:,}"
            role = "👮‍♂️" if u.role == 'admin' else "👤"
            unit = u.unit_number or "?"
            name = u.full_name or "?"
            msg += f"{role} واحد {unit} | {name}\n📱 {u.phone_number or '-'}\n💰 تراز: {bal_str} | 🆔 `{u.telegram_id}`\n---\n"
            
        kb = [[InlineKeyboardButton("➕ ثبت ساکن", callback_data="adm_add_user_start"), InlineKeyboardButton("✏️ ویرایش", callback_data="adm_edit_user_start")], [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
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
            db.add(u)
            db.commit()
            await update.message.reply_text("✅ ثبت شد.")
    finally: db.close()
    await back_to_menu(update, context)
    return ConversationHandler.END

# --- Edit User ---
async def start_edit_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("📝 آیدی عددی یا شماره واحد را وارد کنید:", reply_markup=get_back_button("adm_units"))
    return EDIT_SELECT_USER

async def select_user_to_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inp = update.message.text
    db_gen = get_db(); db = next(db_gen)
    
    if inp.isdigit() and len(inp) > 5: user = db.query(User).filter(User.telegram_id == int(inp)).first()
    else: user = db.query(User).filter(User.unit_number == inp).first()
    
    if not user:
        await update.message.reply_text("❌ یافت نشد.")
        db.close(); return EDIT_SELECT_USER
    
    context.user_data['edit_uid'] = user.id
    db.close()
    
    kb = [
        [InlineKeyboardButton("نام", callback_data="e_name"), InlineKeyboardButton("واحد", callback_data="e_unit")],
        [InlineKeyboardButton("موبایل", callback_data="e_phone"), InlineKeyboardButton("موجودی (اصلاح)", callback_data="e_balance")],
        [InlineKeyboardButton("🔙", callback_data="adm_units")]
    ]
    await update.message.reply_text(f"✅ ویرایش: {user.full_name}", reply_markup=InlineKeyboardMarkup(kb))
    return EDIT_CHOOSE_FIELD

async def choose_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data['edit_field'] = query.data.split("_")[1]
    if context.user_data['edit_field'] == "balance":
        await query.edit_message_text("💰 موجودی جدید را وارد کنید.\n(سیستم خودکار تراکنش اصلاحی ثبت می‌کند)", reply_markup=get_back_button("adm_units"))
    else:
        await query.edit_message_text("مقدار جدید:", reply_markup=get_back_button("adm_units"))
    return EDIT_GET_VALUE

async def save_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    field = context.user_data['edit_field']
    uid = context.user_data['edit_uid']
    
    db_gen = get_db(); db = next(db_gen)
    try:
        u = db.query(User).filter(User.id == uid).first()
        if u:
            if field == "balance":
                try:
                    new_bal = int(val.replace(',', ''))
                    diff = new_bal - u.balance
                    if diff != 0:
                        ttype = 'payment' if diff > 0 else 'charge'
                        t = Transaction(user_id=u.id, type=ttype, amount=abs(diff), description="اصلاح دستی مدیر", status='approved', date=datetime.now())
                        db.add(t)
                        u.balance = new_bal
                        await update.message.reply_text(f"✅ موجودی اصلاح شد.\nتراکنش {ttype} ثبت گردید.")
                except: await update.message.reply_text("❌ عدد نامعتبر.")
            else:
                if field == "name": u.full_name = val
                elif field == "unit": u.unit_number = val
                elif field == "phone": u.phone_number = val
                await update.message.reply_text("✅ ذخیره شد.")
            db.commit()
    finally: db.close()
    await back_to_menu(update, context)
    return ConversationHandler.END


# ==========================================
# 2. EXPENSES (WITH RECEIPT)
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
    if d == "امروز": d = get_current_jalali()
    try: context.user_data['date'] = jalali_to_greg(d)
    except: await update.message.reply_text("❌ فرمت غلط."); return EXP_DATE
    await update.message.reply_text("📝 توضیحات:")
    return EXP_DESC

async def receive_exp_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['desc'] = update.message.text
    await update.message.reply_text("📸 عکس رسید را بفرستید (یا /skip):")
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
        t = Transaction(
            type='expense', amount=context.user_data['amt'], date=context.user_data['date'], 
            description=context.user_data['desc'], receipt_image=filename, status='approved'
        )
        db.add(t); db.commit()
        await update.message.reply_text("✅ هزینه ثبت شد.")
    finally: db.close()
    await back_to_menu(update, context)


# ==========================================
# 3. REQUESTS
# ==========================================
async def admin_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    db_gen = get_db(); db = next(db_gen)
    try:
        reqs = db.query(Transaction).options(joinedload(Transaction.user)).filter(Transaction.status == 'pending').all()
        if not reqs: await query.edit_message_text("✅ درخواستی نیست.", reply_markup=get_back_button()); return
        kb = []
        for r in reqs: kb.append([InlineKeyboardButton(f"💰 {r.amount:,} | {r.user.full_name}", callback_data=f"adm_decide_{r.id}")])
        kb.append([InlineKeyboardButton("🔙", callback_data="main_menu")])
        await query.edit_message_text("📥 درخواست‌ها:", reply_markup=InlineKeyboardMarkup(kb))
    finally: db.close()

async def request_decision_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    tid = int(query.data.split("_")[2])
    db_gen = get_db(); db = next(db_gen)
    try:
        t = db.query(Transaction).options(joinedload(Transaction.user)).filter(Transaction.id == tid).first()
        if not t: await query.edit_message_text("❌ یافت نشد."); return
        
        msg = f"💰 {t.amount:,}\n👤 {t.user.full_name}\n📅 {greg_to_jalali(t.date)}\n📝 {t.description or ''}"
        kb = [[InlineKeyboardButton("✅ تایید", callback_data=f"adm_approve_{tid}"), InlineKeyboardButton("❌ رد", callback_data=f"adm_reject_{tid}")], [InlineKeyboardButton("🔙", callback_data="adm_requests")]]
        
        if t.receipt_image:
            await query.message.delete()
            await context.bot.send_photo(query.message.chat_id, open(t.receipt_image, 'rb'), caption=msg, reply_markup=InlineKeyboardMarkup(kb))
        else: await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    finally: db.close()

async def perform_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    act, tid = query.data.split("_")[1], int(query.data.split("_")[2])
    db_gen = get_db(); db = next(db_gen)
    try:
        t = db.query(Transaction).options(joinedload(Transaction.user)).filter(Transaction.id == tid).first()
        if t and t.status == 'pending':
            if act == "approve":
                t.status = "approved"
                t.user.balance += t.amount
                res = "✅ تایید شد."
                try: await context.bot.send_message(t.user.telegram_id, f"✅ واریزی {t.amount:,} تایید شد.")
                except: pass
            else:
                t.status = "rejected"
                res = "❌ رد شد."
                try: await context.bot.send_message(t.user.telegram_id, "❌ واریزی رد شد.")
                except: pass
            db.commit()
            await context.bot.send_message(query.message.chat_id, res)
            try: await query.message.delete()
            except: pass
            await back_to_menu(update, context)
    finally: db.close()


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
        
        msg = f"⚙️ **تنظیمات**\n💳 کارت: `{card}`\n💰 شارژ ماه: `{charge}`\n📅 روز سررسید: `{due}`\n💾 موجودی اولیه صندوق: `{init_val:,}`"
        kb = [
            [InlineKeyboardButton("کارت", callback_data="adm_set_card"), InlineKeyboardButton("شارژ ماهانه", callback_data="adm_set_charge")],
            [InlineKeyboardButton("روز سررسید", callback_data="adm_set_due"), InlineKeyboardButton("موجودی اولیه", callback_data="adm_set_initial")],
            [InlineKeyboardButton("🔙", callback_data="main_menu")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    finally: db.close()

async def start_edit_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    key_map = {"adm_set_card": "card_number", "adm_set_charge": "monthly_charge", "adm_set_due": "charge_due_day", "adm_set_initial": "initial_fund"}
    cb = query.data
    if cb in key_map:
        context.user_data['set_key'] = key_map[cb]
        txt = "💎 مبلغ موجودی اولیه صندوق:" if context.user_data['set_key'] == "initial_fund" else "مقدار جدید:"
        await query.edit_message_text(txt, reply_markup=get_back_button("adm_settings"))
        return SETTING_VAL
    return ConversationHandler.END

async def save_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    key = context.user_data.get('set_key')
    db_gen = get_db(); db = next(db_gen)
    try:
        if key == "initial_fund":
            try:
                amt = int(val)
                db.query(Transaction).filter(Transaction.type == 'initial').delete()
                t = Transaction(type='initial', amount=amt, description="تنظیم موجودی اولیه", status='approved', date=datetime.now())
                db.add(t)
                await update.message.reply_text(f"✅ موجودی اولیه روی {amt:,} تنظیم شد.")
            except: await update.message.reply_text("❌ عدد وارد کنید.")
        else:
            if key in ["monthly_charge", "charge_due_day"] and not val.isdigit(): await update.message.reply_text("❌ عدد وارد کنید.")
            else:
                set_setting_value(db, key, val)
                await update.message.reply_text("✅ ذخیره شد.")
        db.commit()
    finally: db.close()
    await admin_settings(update, context)
    return ConversationHandler.END

async def cancel_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ لغو شد.")
    await back_to_menu(update, context)
    return ConversationHandler.END


# ==========================================
# 5. MESSAGING
# ==========================================
async def admin_message_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    kb = [[InlineKeyboardButton("📢 همه ساکنین", callback_data="msg_all")], [InlineKeyboardButton("⚠️ بدهکاران", callback_data="msg_debt")], [InlineKeyboardButton("🏠 واحد خاص", callback_data="msg_unit")], [InlineKeyboardButton("🔙", callback_data="main_menu")]]
    await query.edit_message_text("📨 گیرنده:", reply_markup=InlineKeyboardMarkup(kb))
    return MSG_SELECT_TYPE

async def receive_msg_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data['m_type'] = query.data
    if query.data == "msg_unit":
        await query.edit_message_text("🔢 شماره واحد:", reply_markup=get_back_button("main_menu"))
        return MSG_GET_TARGET
    await query.edit_message_text("📝 متن پیام:", reply_markup=get_back_button("main_menu"))
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

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ لغو شد.")
    await back_to_menu(update, context)
    return ConversationHandler.END


# ==========================================
# 6. REPORTS
# ==========================================
async def admin_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.message.reply_text("⏳ ...")
    db_gen = get_db(); db = next(db_gen)
    try:
        wb = openpyxl.Workbook()
        ws = wb.active; ws.title = "ساکنین"
        ws.append(["ID", "نام", "واحد", "تلفن", "بدهی", "پرداختی", "تراز"])
        for u in db.query(User).filter(User.role == 'resident').all():
            c = db.query(func.sum(Transaction.amount)).filter(Transaction.user_id==u.id, Transaction.type=='charge').scalar() or 0
            p = db.query(func.sum(Transaction.amount)).filter(Transaction.user_id==u.id, Transaction.type=='payment', Transaction.status=='approved').scalar() or 0
            ws.append([u.telegram_id, u.full_name, u.unit_number, u.phone_number, c, p, u.balance])
            
        ws2 = wb.create_sheet("تراکنش‌ها")
        ws2.append(["ID", "کاربر", "نوع", "مبلغ", "تاریخ", "توضیحات"])
        for t in db.query(Transaction).options(joinedload(Transaction.user)).all():
            un = t.user.full_name if t.user else "سیستم"
            ws2.append([t.id, un, t.type, t.amount, greg_to_jalali(t.date), t.description])
            
        ws3 = wb.create_sheet("صندوق")
        pay = db.query(func.sum(Transaction.amount)).filter(Transaction.type == 'payment', Transaction.status == 'approved').scalar() or 0
        init = db.query(func.sum(Transaction.amount)).filter(Transaction.type == 'initial').scalar() or 0
        exp = db.query(func.sum(Transaction.amount)).filter(Transaction.type == 'expense').scalar() or 0
        net = (pay + init) - exp
        ws3.append(["دریافتی", pay]); ws3.append(["اولیه", init]); ws3.append(["هزینه", exp]); ws3.append(["موجودی", net])
        
        wb.save("report.xlsx")
        await context.bot.send_document(query.message.chat_id, open("report.xlsx", 'rb'), caption="📊 گزارش")
        os.remove("report.xlsx")
        await back_to_menu(update, context)
    finally: db.close()

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

async def cancel_op(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query: await query.answer(); await back_to_menu(update, context)
    return ConversationHandler.END
