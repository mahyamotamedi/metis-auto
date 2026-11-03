اتصال مستقیم به TypeSafe AI
TypeSafe AI برای استخراج خروجی‌های ساختاریافته از متن استفاده می‌شود. با استفاده از متیس می‌توانید بدون ساخت حساب جداگانه در TypeSafe، درخواست‌های System One را با کلید API متیس خود ارسال کنید.

ابتدا از متیس کلید API دریافت کنید و درخواست را به آدرس زیر بفرستید:

https://api.metisai.ir/typesafe/v1/systemone

کلید متیس باید در هدر Authorization و با پیشوند Bearer ارسال شود.

مدل پشتیبانی‌شده
در حال حاضر مدل jev-latest از طریق این اندپوینت در دسترس است.

نمونه درخواست
در این مثال، متن یک پیام پشتیبانی در فیلد state ارسال می‌شود و TypeSafe سه پاسخ ساختاریافته تولید می‌کند: تیم مناسب برای رسیدگی، میزان نارضایتی و فوری‌بودن پیام.

curl --request POST 'https://api.metisai.ir/typesafe/v1/systemone' \
--header 'Authorization: Bearer YOUR_METIS_API_KEY' \
--header 'Content-Type: application/json' \
--data '{
  "state": "I have been trying to connect my account for three days and the integration keeps failing. Please help ASAP.",
  "model": "jev-latest",
  "questions": {
    "department": {
      "type": "choice",
      "instructions": "Which team should handle this?",
      "criteria": {
        "billing": "Payment or subscription issues",
        "technical": "Bugs or integration problems",
        "sales": "Pricing or account questions"
      }
    },
    "frustration": {
      "type": "score",
      "instructions": "How frustrated does the customer appear?",
      "criteria": [
        "Calm, just stating facts",
        "Frustrated but civil",
        "Very angry, strong language"
      ]
    },
    "is_urgent": {
      "type": "noul",
      "instructions": "The message conveys urgency or time-sensitivity"
    }
  }
}'


نمونه پاسخ
مقادیر دقیق پاسخ به متن ورودی بستگی دارند. ساختار پاسخ به شکل زیر است:

{
  "model": "jev-1.13.0",
  "answers": {
    "department": {
      "type": "choice",
      "choice": "technical",
      "confidence": 0.78,
      "probabilities": {
        "technical": 0.85,
        "sales": 0.0,
        "billing": 0.15
      }
    },
    "frustration": {
      "type": "score",
      "score": 1.0,
      "confidence": 1.0,
      "legend": {
        "0": "Calm, just stating facts",
        "1": "Frustrated but civil",
        "2": "Very angry, strong language"
      }
    },
    "is_urgent": {
      "type": "noul",
      "noul": 1.0
    }
  },
  "usage": {
    "input_tokens": 392,
    "output_tokens": 65
  }
}

نام مدل در پاسخ
مقدار model در درخواست باید jev-latest باشد. TypeSafe ممکن است در پاسخ، نسخه‌ی دقیق مدلی را که درخواست را پردازش کرده است نمایش دهد؛ بنابراین متفاوت‌بودن نام مدل در درخواست و پاسخ طبیعی است.

برای آشنایی با انواع سؤال‌ها، فیلدهای کامل درخواست و جزئیات پاسخ، راهنمای شروع سریع TypeSafe را مطالعه کنید.