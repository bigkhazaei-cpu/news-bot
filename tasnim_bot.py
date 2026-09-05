import os
import requests
import feedparser
from bs4 import BeautifulSoup
from supabase import create_client
from google import genai
from dotenv import load_dotenv

# ----------------------------------------------------
# ۱. بارگذاری فایل env (برای اجرا در سیستم لوکال) و خواندن متغیرها
# ----------------------------------------------------
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("❌ خطا: متغیرهای SUPABASE_URL یا SUPABASE_KEY ست نشده‌اند!")

# اتصال به دیتابیس سوبابیس
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# اتصال به جمینای (در صورت وجود API Key)
ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ----------------------------------------------------
# ۲. دریافت نرخ دلار و ارزهای دیجیتال
# ----------------------------------------------------
def fetch_market_prices():
    """دریافت قیمت دلار (تتر) و ثبت در جدول market_prices"""
    print("🔄 در حال دریافت قیمت‌های بازار...")
    try:
        url = "https://api.nobitex.ir/v2/orderbook/USDTIRT"
        response = requests.get(url, headers=HEADERS, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            usdt_toman = int(data['bids'][0][0]) // 10  # تبدیل ریال به تومان
            
            price_data = {
                "usd_toman": usdt_toman,
                "source": "Nobitex"
            }
            
            print(f"✅ نرخ دلار/تتر: {usdt_toman:,} تومان")
            
            try:
                supabase.table("market_prices").insert(price_data).execute()
                print("💾 قیمت بازار در Supabase ذخیره شد.")
            except Exception as db_err:
                print(f"⚠️ خطا در ذخیره قیمت در دیتابیس (جدول market_prices را بررسی کنید): {db_err}")
                
            return price_data
    except Exception as e:
        print(f"❌ خطا در دریافت قیمت بازار: {e}")
    return None

# ----------------------------------------------------
# ۳. خلاصه‌سازی متن خبر با Gemini
# ----------------------------------------------------
def summarize_text(text):
    """خلاصه‌سازی متن خبر در یک یا دو جمله با استفاده از هوش مصنوعی"""
    if not ai_client or not text:
        return text[:150] + "..." if text else ""
    
    try:
        prompt = f"این خبر را در حداکثر دو جمله کوتاه و مفید به زبان فارسی خلاصه کن:\n\n{text}"
        response = ai_client.models.generate_content(
            model='gemini-1.5-flash',  # مدل اصلاح شده
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        print(f"⚠️ خطا در خلاصه سازی با Gemini: {e}")
        return text[:150] + "..."

# ----------------------------------------------------
# ۴. استخراج اخبار از منابع مختلف (RSS)
# ----------------------------------------------------
def fetch_multi_source_news():
    """استخراج جدیدترین اخبار از تسنیم، ایرنا و ایسنا"""
    sources = {
        "تسنیم": "https://www.tasnimnews.com/fa/rss/feed/0/7/0/",
        "ایرنا": "https://www.irna.ir/rss",
        "ایسنا": "https://www.isna.ir/rss"
    }
    
    processed_news = []
    
    for source_name, rss_url in sources.items():
        print(f"🔄 در حال دریافت اخبار از {source_name}...")
        try:
            feed = feedparser.parse(rss_url)
            
            for entry in feed.entries[:3]:
                title = entry.title
                link = entry.link
                raw_summary = getattr(entry, 'summary', '')
                
                clean_summary = BeautifulSoup(raw_summary, "html.parser").get_text() if raw_summary else title
                final_summary = summarize_text(clean_summary)
                
                news_item = {
                    "title": title,
                    "link": link,
                    "summary": final_summary,
                    "source": source_name
                }
                
                processed_news.append(news_item)
                print(f"  📌 [{source_name}] {title[:40]}...")
                
        except Exception as e:
            print(f"❌ خطا در دریافت اخبار از {source_name}: {e}")
            
    return processed_news

# ----------------------------------------------------
# ۵. ذخیره‌سازی اخبار در Supabase
# ----------------------------------------------------
def save_news_to_supabase(news_list):
    """ثبت اخبار در جدول news دیتابیس سوبابیس"""
    if not news_list:
        print("ℹ️ خبری برای ذخیره‌سازی وجود ندارد.")
        return

    print(f"💾 در حال ذخیره‌سازی {len(news_list)} خبر در Supabase...")
    for item in news_list:
        try:
            check_exist = supabase.table("news").select("id").eq("link", item["link"]).execute()
            
            if not check_exist.data:
                supabase.table("news").insert(item).execute()
                print(f"  ✅ ثبت شد: {item['title'][:30]}...")
            else:
                print(f"  ⏭️ تکراری (نادیده گرفته شد): {item['title'][:30]}...")
        except Exception as e:
            print(f"❌ خطا در ثبت خبر در دیتابیس: {e}")

# ----------------------------------------------------
# ۶. نقطه ورود و اجرای اصلی اسکریپت
# ----------------------------------------------------
def main():
    print("🚀 شروع به کار ربات اخبار و قیمت‌های بازار...")
    
    fetch_market_prices()
    news = fetch_multi_source_news()
    save_news_to_supabase(news)
    
    print("🎉 تمام مراحل با موفقیت به پایان رسید.")

if __name__ == "__main__":
    main()
