from datetime import datetime
from telegram.ext import ContextTypes
from sqlalchemy.orm import Session
from database.core import get_db
from database.models import User, Transaction, BotSetting
from utils.jalali_helper import get_current_jalali

# --- Helper Functions ---
def get_setting(db: Session, key: str, default: str = None):
    """Helper to fetch a setting value from DB."""
    s = db.query(BotSetting).filter(BotSetting.key == key).first()
    return s.value if s else default

def set_setting(db: Session, key: str, value: str):
    """Helper to save/update a setting value in DB."""
    s = db.query(BotSetting).filter(BotSetting.key == key).first()
    if not s:
        s = BotSetting(key=key, value=value)
        db.add(s)
    else:
        s.value = value
    db.commit()

# --- Monthly Charge Job ---
async def monthly_charge_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Scheduled job to apply monthly building charge to all residents.
    Runs daily (configured in main.py).
    
    Logic:
    1. Checks if today is the 'Due Day' set by admin.
    2. Checks if charge has already been applied for this Month-Year.
    3. If conditions met:
       - Creates a debt transaction ('charge') for each resident.
       - Decreases user balance.
       - Sends notification to users.
       - Updates 'last_charge_ym' setting to prevent double charging.
    """
    today = datetime.now()
    # Create a key for Year-Month (e.g., "2025-11")
    ym_key = f"{today.year}-{today.month:02d}"
    
    db_gen = get_db()
    db: Session = next(db_gen)
    
    try:
        # 1. Load Settings
        due_day_str = get_setting(db, "charge_due_day", "1")       # Default 1st of month
        monthly_charge_str = get_setting(db, "monthly_charge", "0") # Default 0
        last_charge_ym = get_setting(db, "last_charge_ym", None)    # Last time charged
        
        # Convert settings to int
        try:
            due_day = int(due_day_str)
        except ValueError:
            due_day = 1
            
        try:
            monthly_charge = int(monthly_charge_str)
        except ValueError:
            monthly_charge = 0
        
        # 2. Validations
        # If charge amount is 0, do nothing
        if monthly_charge <= 0:
            return
        
        # Only run if today is the Due Day
        if today.day != due_day:
            return
        
        # Check if already charged this month
        if last_charge_ym == ym_key:
            # Already charged for this month, skip
            return
        
        # 3. Apply Charge
        residents = db.query(User).filter(User.role == 'resident').all()
        
        if not residents:
            return
            
        jalali_today = get_current_jalali()
        count = 0
        
        for u in residents:
            # Create Debt Transaction (Type: 'charge')
            # This transaction records that user owes money for this month
            txn = Transaction(
                user_id=u.id,
                type='charge',  # Important: Distinguishes from building expenses
                amount=monthly_charge,
                description=f"شارژ ماهانه خودکار - {jalali_today}",
                status='approved', # Automatically approved
                date=today
            )
            db.add(txn)
            
            # Decrease Balance (User becomes deeper in debt or uses credit)
            u.balance -= monthly_charge
            count += 1
            
            # 4. Notify User
            try:
                await context.bot.send_message(
                    chat_id=u.telegram_id,
                    text=(
                        "🏢 **یادآوری شارژ ساختمان**\n\n"
                        f"💰 مبلغ شارژ این ماه: {monthly_charge:,} تومان\n"
                        f"📅 تاریخ اعمال: {jalali_today}\n\n"
                        "این مبلغ به حساب بدهی شما منظور شد.\n"
                        "لطفاً جهت تسویه حساب، از منوی ربات اقدام به پرداخت نمایید."
                    ),
                    parse_mode="Markdown"
                )
            except Exception:
                # User might have blocked the bot
                pass
            
        # 5. Save State
        # Mark this month as charged
        set_setting(db, "last_charge_ym", ym_key)
        db.commit()
        
        print(f"✅ Monthly charge applied for {ym_key} to {count} residents.")
        
    except Exception as e:
        print(f"❌ Error in monthly_charge_job: {e}")
    finally:
        db.close()
