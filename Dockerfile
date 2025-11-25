# استفاده از نسخه سبک پایتون
FROM python:3.11-slim

# تنظیم دایرکتوری کاری داخل کانتینر
WORKDIR /app

# تنظیم متغیرهای محیطی پایتون (برای جلوگیری از تولید فایل‌های pyc و بافر شدن لاگ‌ها)
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# تنظیم تایم‌زون (اختیاری، برای اینکه لاگ‌ها به وقت ایران باشد)
ENV TZ=Asia/Tehran

# نصب پکیج‌های سیستم‌عامل که ممکن است نیاز باشد (مثل curl یا ابزار تایم‌زون)
RUN apt-get update && \
    apt-get install -y --no-install-recommends tzdata && \
    rm -rf /var/lib/apt/lists/*

# کپی کردن فایل نیازمندی‌ها
COPY requirements.txt .

# نصب کتابخانه‌های پایتون
RUN pip install --no-cache-dir -r requirements.txt

# کپی کردن کل کدهای پروژه به داخل کانتینر
COPY . .

# ساخت پوشه‌های مدیا برای جلوگیری از خطا در اولین اجرا
RUN mkdir -p media/receipts media/expenses

# دستور اجرای ربات
CMD ["python", "main.py"]
