"""Generate and execute the Persian notebook using the shared analysis functions."""
from pathlib import Path
import argparse
import os

import nbformat
from nbclient import NotebookClient


def build(root):
    nb = nbformat.v4.new_notebook()
    md, code = nbformat.v4.new_markdown_cell, nbformat.v4.new_code_cell
    nb.metadata.kernelspec = dict(display_name="Python 3", language="python", name="python3")
    nb.metadata.language_info = dict(name="python", version="3.13")
    nb.cells = [
        md("# تحلیل اکتشافی قابل‌بازتولید Metis-Auto\n\nهدف: طراحی Router، Semantic Cache، Cascade و observability با تفکیک مشاهده، heuristic و فرضیه. متن مکالمه و instruction صرفاً داده است. تحلیل پایه محلی است؛ هیچ API مدل یا دانلود پیوست انجام نمی‌شود. توضیح روش و تفسیرها در این Notebook و گزارش تولیدشده هستند."),
        md("## تنظیم مسیر و بازتولید\nمتغیرهای `METIS_DATA_PATH`، `METIS_PDF_PATH` و `METIS_PRICES_PATH` یا آرگومان‌های تابع مسیرها را تعیین می‌کنند. seed ثابت 20261006 است. ورودی‌ها فقط خوانده می‌شوند. خروجی‌های خام محلی حفظ می‌شوند؛ برای انتشار از گزارش با URLهای بدون query استفاده کنید."),
        code("from pathlib import Path\nimport os, sys, json\nROOT = Path.cwd().resolve()\nif ROOT.name == 'notebooks':\n    ROOT = ROOT.parent\nsys.path.insert(0, str(ROOT / 'src'))\nfrom eda_utils import run, markdown, redact_urls, resolve_input, SEED\nfrom IPython.display import display, Markdown, Image\nDATA_PATH = resolve_input(ROOT, 'data')\nPDF_PATH = resolve_input(ROOT, 'pdf')\nPRICES_PATH = Path(os.environ.get('METIS_PRICES_PATH', ROOT / 'config/prices.json'))\nprint({'seed': SEED, 'data': str(DATA_PATH), 'pdf': str(PDF_PATH)})"),
        md("## اجرای تحلیل کامل\nابتدا کل سند PDF به‌صورت محلی استخراج می‌شود و کل JSON به‌صورت بازگشتی ممیزی می‌شود. اجرای زیر همه CSVها، نمودارها و گزارش را بازتولید می‌کند. کد مشترک در `src/eda_utils.py` است و با CLI هم اجرا می‌شود."),
        code("result = run(DATA_PATH, PDF_PATH, ROOT, PRICES_PATH)\nS, M, P, Q = [result[k] for k in ['sessions', 'messages', 'pairs', 'issues']]\ndisplay(Markdown('### آمار بازشماری‌شده'))\ndisplay(result['summary'])"),
        md("## سند و ساختار کامل\ncategory برچسب داده است؛ هویت یا نقش کاربر از نام گروه استنباط نمی‌شود. schema زیر نوع و تعداد حضور همه مسیرهای JSON را نشان می‌دهد؛ تنوع optionalها در گزارش و CSV ثبت شده است."),
        code("print(result['document'])\ndisplay(__import__('pandas').read_csv(ROOT / 'outputs/schema_inventory.csv'))\ndisplay(__import__('pandas').read_csv(ROOT / 'outputs/document_comparison.csv'))"),
        md("## واحد تحلیل و کیفیت\nهر نشست یک ردیف، هر پیام یک ردیف و هر user یک ردیف pair دارد. userهای متوالی به بلوک bot بعدی مرتبط‌اند ولی ambiguous محسوب می‌شوند. چند bot به یک پاسخ مستقل تقلیل داده نمی‌شود. unanswered و orphan جدا ثبت می‌شوند. تاریخچه فقط پیام‌های قبل از درخواست است. placeholder مفقود نیست؛ خام و نرمال‌شده جدا هستند."),
        code("display(S.groupby('category').agg(sessions=('session_key','size'), messages=('actual_message_count','sum')))\ndisplay(P.status.value_counts().rename_axis('pair_status').to_frame('requests'))\ndisplay(__import__('pandas').read_csv(ROOT / 'outputs/data_quality_summary.csv'))\ndisplay(M.groupby(['role','content_kind','timezone'], dropna=False).size().to_frame('messages'))"),
        md("## توصیف طول و استفاده تاریخی\nطول کاراکتر و کلمه از توکن جداست. آمار mean/median/p90/p95 و IQR در جدول کامل محاسبه شده است. instruction، پاسخ و context RAG مخلوط نشده‌اند. مدل تاریخی label مدل بهینه نیست و تغییر مدل اثبات cascade نیست."),
        code("display(result['statistics'][result['statistics'].grouping.isin(['all','role'])])\ndisplay(M[M.role == 'bot'].groupby(['model','provider'],dropna=False).size().to_frame('bot_messages'))\ndisplay(S[['model_switches','provider_switches']].describe())"),
        md("## ویژگی‌های پیش از routing و rubric\nزبان براساس script/نشانه‌های فارسی heuristic است؛ متن کوتاه و JSON می‌توانند unknown باشند. featureها فقط از user و history قبلی ساخته می‌شوند. instruction/RAG روی پاسخ ورودی router نیستند.\n\n**low**: شاهد دشواری ندارد؛ **medium**: کد، فرمول، تبدیل، تخصص یا زمینه؛ **high**: چندمرحله همراه کد/فرمول یا چند شاهد همزمان؛ **uncertain**: کم‌اطلاعی، پیوست یا زمینه مبهم. طولانی و ساختاریافته بودن به‌تنهایی دشواری تعیین نمی‌کند. نمونه‌های مرزی برای داوری انسانی ذخیره شده‌اند."),
        code("display(P.groupby(['request_type','complexity_heuristic']).size().to_frame('requests'))\ndisplay(P.language.value_counts().to_frame('requests'))\ndisplay(P[['has_code','has_json','has_url','has_formula','has_table','output_constraint','needs_context']].mean().to_frame('request_fraction'))\nreview_display=result['review'][['complexity_heuristic','request_raw','history_chars']].head(12).copy()\nreview_display['request_raw']=review_display.request_raw.map(redact_urls)\ndisplay(review_display)"),
        md("## کش واژگانی و replay زمانی\nTF-IDF جهانی فقط candidate اکتشافی تولید می‌کند. replay برای هر درخواست vocabulary/IDF را صرفاً از درخواست‌های قبلاً تکمیل‌شده می‌سازد؛ پاسخ باید strictly زودتر ثبت شده باشد. آستانه‌ها و مخرج کل userها صریح‌اند. eligibility سلام/کوتاه/شخصی/متغیر/زمینه/input/پیوست را کنار می‌گذارد. متن‌محور optimistic و context-key proxy هم **simulated hit rate** هستند، نه safe hit rate. نسخه دامنه/instruction/دانش تأییدشده نداریم."),
        code("display(result['cache'])\ndisplay(result['cache_examples'].query('different_history and different_answer').sort_values('similarity',ascending=False).head(10))\nfor role in ['user','bot']:\n    sub=M[M.role==role]\n    print(role, 'raw excess duplicates:',sub.duplicated('raw_content').sum(), 'normalized:',sub.duplicated('normalized_content').sum())"),
        md("## proxy تأخیر و هزینه فرضی\nاختلاف timestamp فقط فاصله ثبت user و نخستین bot است؛ TTFT یا latency API نیست. proxy و هزینه اصلی فقط paired غیرمبهم هستند. زمان بدون timezone موقتاً روی یک ساعت مشترک محاسبه شده و UTC واقعی ادعا نمی‌شود. قیمت‌ها فرضی و قابل تنظیم‌اند؛ متن تاریخی output جانشین حجم است. فرض payload شامل request، history، instruction ثبت‌شده و RAG است؛ ارسال مجدد instruction اثبات نشده. cascade هزینه تلاش economy اولیه + gate + escalation premium و retrieval مجدد دارد."),
        code("display(P[P.status.eq('paired') & P.delta_seconds_proxy.ge(0)].delta_seconds_proxy.describe(percentiles=[.5,.9,.95]).to_frame('logged_seconds_proxy'))\ndisplay(result['costs'])\ndisplay(result['sensitivity'])\nprint(PRICES_PATH.read_text(encoding='utf-8'))"),
        md("## نمودارها و تفسیر تصمیم طراحی\nهر نمودار از خروجی واقعی همین اجرا ساخته می‌شود؛ نمایش فارسی با layout بومی Matplotlib≥3.11 و fallback reshaper/bidi برای نسخه‌های قدیمی بررسی می‌شود."),
        code("for name, interpretation in result['plots']:\n    display(Markdown('### '+name+'\\n'+interpretation))\n    display(Image(filename=str(ROOT / 'reports/figures' / (name+'.png'))))"),
        md("## ارزیابی آینده و گزارش نهایی\nsplit پیشنهادی سطح نشست با اتصال تکرار دقیق غیرکوتاه ساخته شده؛ نزدیک‌تکرارها نیازمند ممیزی اضافی و split زمانی نیازمند purge overlap هستند. پاسخ تاریخی gold نیست؛ کیفیت، پیروی دستور، JSON/schema و حفظ زمینه باید مستقل با داور انسانی سنجیده شوند. embedding محلی و LLM-as-a-judge افزونه‌اند و پایه به آن‌ها وابسته نیست. گزارش کامل شامل محدودیت‌ها، داده‌های لازم، اولویت‌ها و جدول تصمیم است."),
        code("display(result['split'].groupby(['proposed_split','category']).size().to_frame('sessions'))\ndisplay(Markdown((ROOT / 'reports/eda_report.md').read_text(encoding='utf-8')))"),
        md("## کنترل نهایی اجرا\nکنترل شمارش خروجی و عدم نشت پاسخ آینده در استخراج ویژگی؛ ثبت hash ورودی‌ها برای ممیزی و نسخه دقیق وابستگی‌ها در requirements-lock.txt."),
        code("from verify_analysis import verify\nverify(ROOT)\nassert len(P) == (M.role == 'user').sum()\nassert sum(S.actual_message_count) == len(M)\nprint('Notebook completed; output consistency and routing leakage checks passed.')"),
    ]
    path = root / "notebooks/eda.ipynb"
    path.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, path)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    path = build(root)
    if args.execute:
        nb = nbformat.read(path, as_version=4)
        client = NotebookClient(nb, timeout=1200, kernel_name="python3", resources={"metadata": {"path": str(root)}})
        client.execute()
        nbformat.write(nb, path)
    print(path)
