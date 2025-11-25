from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_setup_choice_keyboard():
    """
    Keyboard for the very first user to choose their role.
    """
    keyboard = [
        [InlineKeyboardButton("👮‍♂️ مدیر ساختمان هستم", callback_data="setup_admin")],
        [InlineKeyboardButton("👤 ساکن هستم", callback_data="setup_resident")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_resident_menu():
    """
    Resident main menu (4 buttons)
    """
    keyboard = [
        [
            InlineKeyboardButton("📊 وضعیت من", callback_data="res_status"),
            InlineKeyboardButton("🏢 وضعیت ساختمان", callback_data="res_building_info") 
        ],
        [
            InlineKeyboardButton("🧾 تراکنش‌های من", callback_data="res_history"),
            InlineKeyboardButton("💳 ثبت پرداختی", callback_data="res_pay")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_menu():
    """
    Admin main menu (9 buttons)
    Added: Archive Reports button
    """
    keyboard = [
        [
            InlineKeyboardButton("🏘 مدیریت واحدها", callback_data="adm_units"),
            InlineKeyboardButton("📥 درخواست‌ها", callback_data="adm_requests")
        ],
        [
            InlineKeyboardButton("💸 ثبت هزینه ساختمان", callback_data="adm_expenses"),
            InlineKeyboardButton("📨 مدیریت پیام‌ها", callback_data="adm_message_menu")
        ],
        [
            InlineKeyboardButton("📉 گزارش‌گیری", callback_data="adm_reports"),
            InlineKeyboardButton("📁 آرشیو گزارش‌ها", callback_data="arch_reports")  # <--- دکمه جدید
        ],
        [
            InlineKeyboardButton("💰 خلاصه صندوق", callback_data="adm_balance_summary"),
            InlineKeyboardButton("⚙️ تنظیمات سیستم", callback_data="adm_settings")
        ],
        [
            InlineKeyboardButton("👤 نمای ساکن", callback_data="adm_view_as_resident")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_button(target="main_menu"):
    """
    General Back button
    target: Callback data to return to (default: main_menu)
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data=target)]
    ])
