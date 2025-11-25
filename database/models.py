from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, BigInteger, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from database.core import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    unit_number = Column(String, nullable=True)
    phone_number = Column(String, nullable=True)
    
    # Roles: 'admin' (Modir), 'resident' (Saken)
    role = Column(String, default="resident")
    
    # Balance Logic:
    #   0  : Settled (Bi-hesab)
    #  > 0 : Credit (Bestankar / Ezafe Pardakht)
    #  < 0 : Debt (Bedehkar / Pardakht Nashode)
    balance = Column(BigInteger, default=0)

    # Relationship to transactions
    transactions = relationship("Transaction", back_populates="user")

    def __repr__(self):
        return f"<User(id={self.telegram_id}, unit={self.unit_number}, role={self.role})>"


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True) 
    # user_id is Nullable because some expenses (like 'expense' or 'initial') 
    # are general building records, not linked to a specific user debt.
    
    # Types:
    # 1. 'payment': Resident pays money (Increases User Balance)
    # 2. 'charge': Monthly automatic charge (Decreases User Balance)
    # 3. 'expense': Building expenditure by Admin (Does NOT affect User Balance directly)
    # 4. 'initial': Initial fund added by admin (Increases Building Net Balance)
    type = Column(String, nullable=False)
    
    amount = Column(BigInteger, nullable=False)
    date = Column(DateTime, default=datetime.now)
    description = Column(Text, nullable=True)
    
    # Path to the receipt image file on server
    receipt_image = Column(String, nullable=True)
    
    # Status: 'pending', 'approved', 'rejected'
    status = Column(String, default="pending")

    user = relationship("User", back_populates="transactions")

    def __repr__(self):
        return f"<Transaction(type={self.type}, amount={self.amount}, status={self.status})>"


class BotSetting(Base):
    """
    Stores dynamic settings for the bot.
    Examples of keys:
      - 'monthly_charge': The amount of monthly charge (e.g., '500000')
      - 'charge_due_day': The day of month to apply charge (e.g., '1')
      - 'card_number': Card number for payments
      - 'last_charge_ym': Last Year-Month that charge was applied (e.g., '2025-11')
      - 'initial_balance': Default balance for NEW users (e.g., '0')
    """
    __tablename__ = "bot_settings"

    key = Column(String, primary_key=True, index=True)
    value = Column(String, nullable=False)

    def __repr__(self):
        return f"<Setting({self.key}={self.value})>"
