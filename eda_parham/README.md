# Metis-Auto — تحلیل اکتشافی داده

تحلیل محلی و قابل‌بازتولید مکالمات فارسی برای تصمیم‌های Router، Semantic Cache، Cascade و Observability. فایل‌های ورودی تغییر نمی‌کنند و هیچ URL پیوست دانلود نمی‌شود. هیچ API پولی لازم نیست.

## نصب و مسیر ورودی

Python 3.11 یا جدیدتر؛ اجرای فعلی با Python 3.13 انجام می‌شود. در ریشه پروژه:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:METIS_DATA_PATH = "C:\Users\Mandish\Desktop\data.json"
$env:METIS_PDF_PATH = "C:\Users\Mandish\Desktop\project-draft.pdf"
```

مسیر پیش‌فرض در نبود متغیرها `data/data.json` و `data/project-draft.pdf` است؛ ورودی‌ها را خودتان در آن مسیر قرار دهید. اگر این مسیرها وجود نداشته باشند، مسیر معتبر اجرای قبلی از `outputs/run_manifest.json` بازیابی می‌شود تا Notebook در همین دستگاه فوراً قابل بازاجرا باشد. آرگومان/متغیر محیطی بر هر دو اولویت دارد. ورودی‌های بزرگ در پروژه کپی نشده‌اند. قیمت فرضی قابل تنظیم در `config/prices.json` است؛ با `METIS_PRICES_PATH` یا `--prices` تغییر دهید. همه قیمت‌ها **فرضی** هستند.

## اجرای تحلیل و Notebook

```powershell
python src/eda_utils.py --data "$env:METIS_DATA_PATH" --pdf "$env:METIS_PDF_PATH"
python src/build_notebook.py --execute
python src/verify_analysis.py
```

دستور دوم Notebook را می‌سازد، همه سلول‌ها را اجرا می‌کند و با خروجی ذخیره می‌کند. خود `notebooks/eda.ipynb` را نیز می‌توان در VS Code یا Jupyter از بالا تا پایین اجرا کرد. Notebook با کد مشترک همه خروجی‌ها را بازتولید می‌کند. برای نسخه دقیق محیط اجرا `requirements-lock.txt` تولید می‌شود؛ seed در کد 20261006 است. `outputs/run_manifest.json` شامل نسخه‌ها و SHA256 ورودی‌ها و قیمت‌هاست.

## فایل‌ها

- `notebooks/eda.ipynb`: توضیحات فارسی، کد اجرایی، جدول‌ها، نمودارها و تفسیرها.
- `src/eda_utils.py`: استخراج PDF، ممیزی بازگشتی JSON، ساخت جداول، ویژگی‌ها، replay و هزینه فرضی.
- `reports/eda_report.md`: گزارش فارسی کامل و جدول نهایی تصمیم.
- `reports/figures/`: نمودارهای PNG و آزمایش نمایش فارسی.
- `outputs/sessions.csv`, `messages.csv`, `request_response_pairs.csv`, `data_quality_issues.csv`: جداول اصلی؛ UTF-8 BOM برای خواندن راحت فارسی در Excel.
- `outputs/schema_inventory.csv`, `document_comparison.csv`, `descriptive_statistics.csv`: ممیزی و آمار.
- `outputs/cache_candidates.csv`, `cache_thresholds.csv`: فرصت واژگانی و replay زمانی.
- `outputs/token_cost_estimates.csv`, `cost_scenarios.csv`, `cost_sensitivity.csv`: برآورد اجزای payload و سناریوها.
- `outputs/session_split_proposal.csv`, `human_review_sample.csv`: split اولیه و نمونه داوری بدون برچسب جعلی.

## قرارداد تحلیل

هر user در pair باقی می‌ماند. userهای متوالی و botهای متوالی `ambiguous_block` هستند؛ botهای ابتدایی orphan ثبت می‌شوند. تاریخچه تنها از پیام‌های قبلی ساخته می‌شود. session_key مبتنی بر موقعیت از ادغام شناسه تکراری جلوگیری می‌کند.

Router به instruction/RAG روی bot یا پاسخ آینده دسترسی ندارد. نوع/زبان/پیچیدگی heuristic است، نه gold. مدل تاریخی فقط مصرف ثبت‌شده را نشان می‌دهد. TF-IDF replay تنها از درخواست‌های قبلاً پاسخ‌داده‌شده fit می‌شود و response باید strictly زودتر ثبت شده باشد. hit rate شبیه‌سازی‌شده صحت کش را اثبات نمی‌کند.

اختلاف timestamp **proxy** است؛ API latency/TTFT نیست. tokenها کاراکتر/۴ با پارامتر قابل تنظیم‌اند؛ هزینه واقعی نیست. اجزای request/history/instruction/RAG/output جدا نگهداری می‌شوند. هزینه سناریوها classifier، retrieval، embedding/cache و تلاش اول cascade را با فرضیات صریح لحاظ می‌کند؛ کیفیت مدل جایگزین آزمایش نشده است.

گزارش query string لینک‌های امضاشده را حذف می‌کند. CSVهای خام برای حفظ داده محلی URL اصلی را نگه می‌دارند؛ هنگام اشتراک عمومی از گزارش و جداول نمونه sanitize‌شده استفاده کنید. نمودار فارسی با DejaVu Sans و layout بومی Matplotlib≥3.11 بررسی می‌شود؛ نسخه‌های قدیمی از arabic-reshaper و python-bidi استفاده می‌کنند.

embedding محلی و LLM-as-a-judge فقط مسیر مرحله بعد هستند؛ در اجرای پایه استفاده نشده‌اند. جزئیات پیش‌نیاز، rubric داوری و observability در گزارش آمده است.
