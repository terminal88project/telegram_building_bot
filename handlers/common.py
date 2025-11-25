from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy.orm import Session
from database.core import get_db
from database.models import User
from utils.keyboards import get_resident_menu, get_admin_menu, get_setup_choice_keyboard

# Try to import ADMIN_ID if configured, else None
try:
    from config import ADMIN_ID
except ImportError:
    ADMIN_ID = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Smart Entry Point:
    1. Checks if user is hardcoded ADMIN_ID -> Admin Menu.
    2. Checks DB for existing user -> Admin/Resident Menu.
    3. If New User -> Shows Role Selection (Setup Choice).
    """
    user_telegram_id = update.effective_user.id
    full_name = update.effective_user.full_name
    
    # Helper to send/edit messages
    async def send(text, markup=None):
        if update.callback_query:
            await update.callback_query.answer()
            try: 
                await update.callback_query.edit_message_text(
                    text=text, 
                    reply_markup=markup, 
                    parse_mode="Markdown"
                )
            except:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, 
                    text=text, 
                    reply_markup=markup, 
                    parse_mode="Markdown"
                )
        else:
            await update.message.reply_text(
                text=text, 
                reply_markup=markup, 
                parse_mode="Markdown"
            )

    db_gen = get_db()
    db: Session = next(db_gen)
    
    try:
        # 1. Check DB for User
        user = db.query(User).filter(User.telegram_id == user_telegram_id).first()

        # 2. Check Hardcoded ADMIN_ID (Optional)
        if ADMIN_ID and user_telegram_id == int(ADMIN_ID):
            if not user:
                user = User(
                    telegram_id=user_telegram_id, 
                    full_name=full_name, 
                    role="admin", 
                    unit_number="مدیرکل",
                    balance=0
                )
                db.add(user)
                db.commit()
            elif user.role != "admin":
                user.role = "admin"
                db.commit()
        
        # 3. Determine Menu based on User Role
        if user:
            # Update name if changed
            if user.full_name != full_name:
                user.full_name = full_name
                db.commit()
            
            if user.role == 'admin':
                await send(f"👮‍♂️ سلام مدیر عزیز ({full_name})، خوش آمدید.", get_admin_menu())
            else:
                unit = user.unit_number if user.unit_number else "نامشخص"
                await send(
                    f"👋 سلام {user.full_name} عزیز.\n"
                    f"🏠 شما به عنوان ساکن **واحد {unit}** شناخته شدید.",
                    get_resident_menu()
                )
        else:
            # 4. New User -> Show Setup Choice
            await send(
                "👋 به ربات مدیریت ساختمان خوش آمدید!\n\n"
                "برای شروع، لطفاً وضعیت خود را مشخص کنید:",
                get_setup_choice_keyboard()
            )

    except Exception as e:
        await send(f"❌ خطا: {e}")
    finally:
        db.close()


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Back button action (calls start)."""
    await start(update, context)


async def handle_setup_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Callback for setup choices:
    - setup_admin: Tries to register as the FIRST admin.
    - setup_resident: Shows ID for admin to add manually.
    """
    query = update.callback_query
    await query.answer()
    
    choice = query.data
    user_id = update.effective_user.id
    full_name = update.effective_user.full_name
    
    db_gen = get_db()
    db: Session = next(db_gen)
    
    try:
        if choice == "setup_admin":
            # Check if ANY admin already exists
            admin_exists = db.query(User).filter(User.role == 'admin').first()
            
            if admin_exists:
                await query.edit_message_text(
                    "❌ قبلاً یک مدیر برای ساختمان تعریف شده است.\n"
                    "شما نمی‌توانید مدیر شوید. اگر ساکن هستید، گزینه دیگر را انتخاب کنید.",
                    parse_mode="Markdown"
                )
            else:
                # Register as First Admin
                new_admin = User(
                    telegram_id=user_id,
                    full_name=full_name,
                    role='admin',
                    unit_number='مدیریت',
                    balance=0
                )
                db.add(new_admin)
                db.commit()
                
                await query.edit_message_text(
                    "✅ تبریک! شما به عنوان **مدیر ساختمان** ثبت شدید.\n"
                    "اکنون به تمام امکانات دسترسی دارید.",
                    parse_mode="Markdown"
                )
                # Show menu immediately
                await context.bot.send_message(
                    chat_id=user_id, 
                    text="پنل مدیریت:", 
                    reply_markup=get_admin_menu()
                )
        
        elif choice == "setup_resident":
            # Instructions for Resident
            await query.edit_message_text(
                "✅ بسیار عالی.\n\n"
                f"برای دسترسی به پنل ساکنین، باید توسط مدیر تایید شوید.\n"
                f"لطفاً این کد را برای مدیر بفرستید تا شما را اضافه کند:\n\n"
                f"`{user_id}`\n\n"
                f"(روی کد بزنید کپی می‌شود)",
                parse_mode="Markdown"
            )
            
    finally:
        db.close()
