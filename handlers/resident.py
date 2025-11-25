from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from sqlalchemy.orm import Session
from sqlalchemy import func
from database.core import get_db
from database.models import User, Transaction, BotSetting
from utils.jalali_helper import greg_to_jalali, jalali_to_greg, get_current_jalali
from utils.keyboards import get_resident_menu, get_back_button
from datetime import datetime
import os

# --- States for Payment Conversation ---
AMOUNT, DATE, DESCRIPTION, RECEIPT = range(4)

# --- Helper: Return to Resident Menu ---
async def back_to_resident_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Returns user to the main resident menu."""
    chat_id = update.effective_chat.id
    context.user_data.clear()
    await context.bot.send_message(
        chat_id=chat_id,
        text="👤 **پنل ساکنین**",
        reply_markup=get_resident_menu(),
        parse_mode="Markdown"
    )

# ==========================================
# 1. VIEW STATUS & TRANSACTIONS
# ==========================================

async def my_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback for '📊 وضعیت من'."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    db_gen = get_db()
    db: Session = next(db_gen)
    
    try:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        
        if user:
            balance = user.balance
            unit = user.unit_number if user.unit_number else "تعیین نشده"
            
            if balance < 0:
                status_text = f"🔴 **بدهکار**: {abs(balance):,} تومان"
            elif balance > 0:
                status_text = f"🟢 **بستانکار**: {balance:,} تومان"
            else:
                status_text = "⚪️ **تصفیه** (بی‌حساب)"
                
            msg = (
                f"👤 **وضعیت حساب شما**\n\n"
                f"🏠 واحد: {unit}\n"
                f"💰 تراز: {balance:,}\n"
                f"{status_text}\n"
            )
            
            await query.edit_message_text(
                text=msg,
                parse_mode="Markdown",
                reply_markup=get_back_button()
            )
    finally:
        db.close()

async def my_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback for '🧾 تراکنش‌های من'."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    db_gen = get_db()
    db: Session = next(db_gen)
    
    try:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        transactions = db.query(Transaction).filter(Transaction.user_id == user.id).order_by(Transaction.date.desc()).limit(5).all()
        
        if not transactions:
            msg = "📭 شما هنوز هیچ تراکنشی ثبت نکرده‌اید."
        else:
            msg = "🧾 **۵ تراکنش آخر شما:**\n\n"
            for t in transactions:
                d_date = greg_to_jalali(t.date)
                icon = "✅" if t.type == 'payment' else "🔻"
                
                if t.status == 'pending': s_icon = "⏳" 
                elif t.status == 'approved': s_icon = "✅"
                else: s_icon = "❌"
                
                desc_text = f"| {t.description}" if t.description else ""
                
                msg += f"{icon} **{t.amount:,}** {d_date}\n"
                msg += f"   {s_icon} {t.status} {desc_text}\n\n"
        
        await query.edit_message_text(
            text=msg,
            parse_mode="Markdown",
            reply_markup=get_back_button()
        )
    finally:
        db.close()

# ==========================================
# 2. BUILDING INFO (VIEW EXPENSES & RECEIPT)
# ==========================================

async def building_info_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    نمایش وضعیت کلی ساختمان و هزینه‌ها برای ساکنین
    """
    query = update.callback_query
    await query.answer()
    
    db_gen = get_db()
    db: Session = next(db_gen)
    try:
        pay = db.query(func.sum(Transaction.amount)).filter(Transaction.type == 'payment', Transaction.status == 'approved').scalar() or 0
        init = db.query(func.sum(Transaction.amount)).filter(Transaction.type == 'initial').scalar() or 0
        exp = db.query(func.sum(Transaction.amount)).filter(Transaction.type == 'expense').scalar() or 0
        net_balance = (pay + init) - exp
        
        last_expenses = db.query(Transaction).filter(Transaction.type == 'expense').order_by(Transaction.date.desc()).limit(5).all()
        
        msg = (
            "🏢 **وضعیت صندوق ساختمان**\n\n"
            f"💎 **موجودی فعلی:** {net_balance:,} تومان\n"
            f"📉 **کل هزینه‌ها:** {exp:,} تومان\n\n"
            "📋 **آخرین هزینه‌ها:**\n"
        )
        
        keyboard = []
        if last_expenses:
            for ex in last_expenses:
                date = greg_to_jalali(ex.date)
                if ex.receipt_image:
                    btn_text = f"📸 فاکتور {ex.amount:,} ({date})"
                    keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"show_receipt_{ex.id}")])
                
                msg += f"🔸 {ex.amount:,} T | {date}\n   └ {ex.description or '-'}\n"
        else:
            msg += "(هزینه‌ای ثبت نشده است)"
            
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
        
        # اگر از حالت نمایش عکس برگشته‌ایم، عکس را پاک کن و متن بفرست
        if query.message.photo:
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=msg,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    finally:
        db.close()

async def show_expense_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show receipt photo with a SINGLE back button."""
    query = update.callback_query
    await query.answer()
    txn_id = int(query.data.split("_")[2])
    
    db_gen = get_db(); db = next(db_gen)
    try:
        txn = db.query(Transaction).filter(Transaction.id == txn_id).first()
        if txn and txn.receipt_image:
            try:
                # دکمه بازگشت ساده که به لیست هزینه‌ها برمی‌گردد
                back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="res_building_info")]])
                
                await query.message.delete()
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=open(txn.receipt_image, 'rb'),
                    caption=f"🧾 فاکتور هزینه: {txn.description}\n💰 مبلغ: {txn.amount:,}",
                    reply_markup=back_kb
                )
            except:
                await context.bot.send_message(
                    chat_id=query.message.chat_id, 
                    text="❌ عکس باز نشد (شاید فایل حذف شده).", 
                    reply_markup=get_back_button("res_building_info")
                )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat_id, 
                text="❌ عکس یافت نشد.", 
                reply_markup=get_back_button("res_building_info")
            )
    finally:
        db.close()

# ==========================================
# 3. PAYMENT FLOW (CONVERSATION)
# ==========================================

async def start_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        text="💰 **ثبت پرداختی جدید**\n\nلطفاً مبلغ واریزی را به تومان وارد کنید:\n(فقط عدد انگلیسی)\n(/cancel برای لغو)",
        parse_mode="Markdown",
        reply_markup=get_back_button("main_menu") 
    )
    return AMOUNT

async def receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text
    if not amount_text.isdigit():
        await update.message.reply_text("❌ لطفاً فقط عدد وارد کنید. دوباره تلاش کنید:")
        return AMOUNT
    
    context.user_data['pay_amount'] = int(amount_text)
    today = get_current_jalali()
    await update.message.reply_text(f"📅 تاریخ واریز را وارد کنید:\n(مثال: {today})\nیا کلمه 'امروز' را بنویسید.")
    return DATE

async def receive_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date_text = update.message.text
    if date_text.strip() == "امروز": date_text = get_current_jalali()
    
    try:
        greg_date = jalali_to_greg(date_text)
        context.user_data['pay_date_obj'] = greg_date
        context.user_data['pay_date_str'] = date_text
    except:
        await update.message.reply_text("❌ تاریخ نامعتبر. دوباره وارد کنید (1402/01/01):")
        return DATE
        
    await update.message.reply_text("📝 توضیحات (اختیاری) را بنویسید یا /skip را بزنید:")
    return DESCRIPTION

async def receive_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['pay_desc'] = update.message.text
    await request_receipt(update)
    return RECEIPT

async def skip_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['pay_desc'] = ""
    await request_receipt(update)
    return RECEIPT

async def request_receipt(update):
    await update.message.reply_text("📸 لطفاً تصویر فیش واریزی را ارسال کنید:\n(یا /skip اگر عکس ندارید)")

async def receive_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo_file = await update.message.photo[-1].get_file()
    
    os.makedirs("media/receipts", exist_ok=True)
    file_path = f"media/receipts/{user.id}_{int(datetime.now().timestamp())}.jpg"
    await photo_file.download_to_drive(file_path)
    
    return await save_payment(update, context, file_path)

async def skip_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await save_payment(update, context, None)

async def save_payment(update: Update, context: ContextTypes.DEFAULT_TYPE, image_path):
    user_id = update.effective_user.id
    amount = context.user_data['pay_amount']
    p_date = context.user_data['pay_date_obj']
    user_desc = context.user_data.get('pay_desc', '')
    
    db_gen = get_db()
    db: Session = next(db_gen)
    try:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        
        new_txn = Transaction(
            user_id=user.id,
            type='payment',
            amount=amount,
            description=user_desc,
            receipt_image=image_path,
            status='pending',
            date=p_date
        )
        db.add(new_txn)
        db.commit()
        
        await update.message.reply_text(
            "✅ **درخواست ثبت شد!**\nبرای مدیر ارسال شد و پس از تایید اعمال می‌شود.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}")
    finally:
        db.close()
        
    await back_to_resident_menu(update, context)
    return ConversationHandler.END

async def cancel_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ عملیات لغو شد.")
    else:
        await update.message.reply_text("❌ عملیات لغو شد.")
        
    await back_to_resident_menu(update, context)
    return ConversationHandler.END
