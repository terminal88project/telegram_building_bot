import sys
import asyncio
import logging
from datetime import time
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    ConversationHandler, MessageHandler, filters
)
from config import BOT_TOKEN
from database.core import init_db
from handlers.common import start, show_menu, handle_setup_choice
from jobs import monthly_charge_job

# Import Resident Handlers
from handlers.resident import (
    my_status, my_transactions, start_payment, building_info_view, show_expense_receipt,
    receive_amount, receive_date, receive_description, skip_description,
    receive_receipt, skip_receipt, cancel_payment, 
    AMOUNT, DATE, DESCRIPTION, RECEIPT
)

# Import Admin Handlers
from handlers.admin import (
    admin_requests, request_decision_view, perform_decision, admin_units,
    # Add User
    start_add_user, receive_new_user_id, receive_new_user_unit, receive_new_user_name, receive_new_user_phone,
    # Edit User
    start_edit_user, select_user_to_edit, choose_edit_field, save_edit_value,
    # Expenses
    start_expense, receive_exp_amount, receive_exp_date, receive_exp_desc, receive_exp_receipt, skip_exp_receipt,
    # Reports & Settings & Other
    admin_reports, admin_balance_summary, admin_settings, admin_view_as_resident,
    # Settings Editing
    start_edit_setting, save_setting,
    # Messaging
    admin_message_menu, receive_msg_type, receive_msg_target, send_message_final,
    # Helper Cancel
    cancel_op,
    # States
    ADD_USER_ID, ADD_USER_UNIT, ADD_USER_NAME, ADD_USER_PHONE,
    EDIT_SELECT_USER, EDIT_CHOOSE_FIELD, EDIT_GET_VALUE,
    EXP_AMOUNT, EXP_DATE, EXP_DESC, EXP_RECEIPT,
    SETTING_VAL, MSG_SELECT_TYPE, MSG_GET_TEXT, MSG_GET_TARGET
)

# Configure Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def run_bot():
    print("🚀 Starting Bot...")
    init_db()
    print("✅ Database initialized.")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # =========================================
    # 1. JOB QUEUE (Scheduled Tasks)
    # =========================================
    app.job_queue.run_daily(
        monthly_charge_job,
        time=time(hour=3, minute=0), 
        name="monthly_charge_job"
    )
    print("⏰ JobQueue started (Monthly Charge Check at 03:00).")


    # =========================================
    # 2. CONVERSATION HANDLERS
    # =========================================
    
    # A. Payment (Resident)
    payment_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_payment, pattern="^res_pay$")],
        states={
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount)],
            DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_date)],
            DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_description),
                CommandHandler("skip", skip_description)
            ],
            RECEIPT: [
                MessageHandler(filters.PHOTO, receive_receipt),
                CommandHandler("skip", skip_receipt)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_payment), 
            CallbackQueryHandler(cancel_payment, pattern="^main_menu$")
        ]
    )
    app.add_handler(payment_handler)

    # B. Add User (Admin)
    add_user_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_user, pattern="^adm_add_user_start$")],
        states={
            ADD_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_user_id)],
            ADD_USER_UNIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_user_unit)],
            ADD_USER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_user_name)],
            ADD_USER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_user_phone)],
        },
        fallbacks=[CallbackQueryHandler(cancel_op, pattern="^adm_units$"), CallbackQueryHandler(cancel_op, pattern="^main_menu$")]
    )
    app.add_handler(add_user_handler)

    # C. Edit User (Admin)
    edit_user_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_edit_user, pattern="^adm_edit_user_start$")],
        states={
            EDIT_SELECT_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_user_to_edit)],
            # Pattern matches e_name, e_unit, e_phone, e_balance
            EDIT_CHOOSE_FIELD: [CallbackQueryHandler(choose_edit_field, pattern="^e_(name|unit|phone|balance)$")],
            EDIT_GET_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit_value)],
        },
        fallbacks=[CallbackQueryHandler(cancel_op, pattern="^adm_units$"), CallbackQueryHandler(cancel_op, pattern="^main_menu$")]
    )
    app.add_handler(edit_user_handler)

    # D. Expenses (Admin) - UPDATED WITH RECEIPT
    expense_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_expense, pattern="^adm_expenses$")],
        states={
            EXP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_exp_amount)],
            EXP_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_exp_date)],
            EXP_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_exp_desc)],
            EXP_RECEIPT: [
                MessageHandler(filters.PHOTO, receive_exp_receipt),
                CommandHandler("skip", skip_exp_receipt)
            ]
        },
        fallbacks=[CallbackQueryHandler(cancel_op, pattern="^main_menu$")]
    )
    app.add_handler(expense_handler)

    # E. Settings Edit (Admin)
    settings_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_edit_setting, pattern="^adm_set_")
        ],
        states={
            SETTING_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_setting)],
        },
        fallbacks=[CallbackQueryHandler(cancel_op, pattern="^adm_settings$"), CallbackQueryHandler(cancel_op, pattern="^main_menu$")]
    )
    app.add_handler(settings_handler)

    # F. Messaging (Admin)
    msg_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_message_menu, pattern="^adm_message_menu$")],
        states={
            MSG_SELECT_TYPE: [CallbackQueryHandler(receive_msg_type, pattern="^msg_type_")],
            MSG_GET_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_msg_target)],
            MSG_GET_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_message_final)],
        },
        fallbacks=[CallbackQueryHandler(cancel_op, pattern="^main_menu$")]
    )
    app.add_handler(msg_handler)


    # =========================================
    # 3. CALLBACK HANDLERS
    # =========================================
    
    # Setup Choice (First Run)
    app.add_handler(CallbackQueryHandler(handle_setup_choice, pattern="^setup_(admin|resident)$"))

    # Admin
    app.add_handler(CallbackQueryHandler(admin_requests, pattern="^adm_requests$"))
    app.add_handler(CallbackQueryHandler(request_decision_view, pattern="^adm_decide_"))
    app.add_handler(CallbackQueryHandler(perform_decision, pattern="^adm_(approve|reject)_"))
    app.add_handler(CallbackQueryHandler(admin_units, pattern="^adm_units$"))
    app.add_handler(CallbackQueryHandler(admin_reports, pattern="^adm_reports$"))
    app.add_handler(CallbackQueryHandler(admin_balance_summary, pattern="^adm_balance_summary$"))
    app.add_handler(CallbackQueryHandler(admin_settings, pattern="^adm_settings$"))
    app.add_handler(CallbackQueryHandler(admin_view_as_resident, pattern="^adm_view_as_resident$"))

    # Resident
    app.add_handler(CallbackQueryHandler(my_status, pattern="^res_status$"))
    app.add_handler(CallbackQueryHandler(my_transactions, pattern="^res_history$"))
    app.add_handler(CallbackQueryHandler(building_info_view, pattern="^res_building_info$"))
    app.add_handler(CallbackQueryHandler(show_expense_receipt, pattern="^show_receipt_")) # NEW

    # Common
    app.add_handler(CallbackQueryHandler(show_menu, pattern="^main_menu$"))
    app.add_handler(CommandHandler("start", start))


    # =========================================
    # 4. START BOT
    # =========================================
    print("🤖 Bot is polling...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    stop_signal = asyncio.Future()
    try:
        await stop_signal
    except asyncio.CancelledError:
        pass
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

def main():
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped.")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == '__main__':
    main()
