import os
import re
import time
import math
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client
from dotenv import load_dotenv
from google import genai

# ۱. بارگذاری متغیرهای محیطی از فایل .env
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# بررسی و تایید وجود متغیرها
if not SUPABASE_URL or not SUPABASE_KEY or "your_supabase" in SUPABASE_KEY:
    print(f"❌ خطا: متغیرهای SUPABASE_URL یا SUPABASE_KEY در فایل .env معتبر نیستند!")
    exit(1)

# ۲. اتصال به Supabase و Gemini AI
try:
    supabase: Client = create_client(SUPABASE_URL.strip(), SUPABASE_KEY.strip())
    print("✅ اتصال موفقیت‌آمیز به Supabase برقرار شد.")
except Exception as e:
    print(f"❌ خطا در ساخت کلاینت Supabase: {e}")
    exit(1)

ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

URL = "https://www.tasnimnews.ir/fa/service/1/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "fa,en;q=0.9",
}

def get_reading_time(text: str) -> int:
    """محاسبه زمان مطالعه بر اساس کلمات"""
    words = len(text.split())
    return max(1, math.ceil(words / 200))

def summarize_with_ai(full_text: str) -> str:
    """خلاصه‌سازی متن خبر با Gemini"""
    if not ai_client:
        return full_text[:150] + "..."  # جایگزین در صورت عدم تنظیم کلید AI
    
    try:
        prompt = (
            "متن خبر زیر را خوانده و یک خلاصه جذاب در حداکثر ۲ تا ۳ جمله کوتاه (حدود ۵0 کلمه) "
            "به زبان فارسی بنویس. فقط متن خلاصه را خروجی بده:\n\n" + full_text
        )
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        print(f"⚠️ خطا در خلاصه‌سازی AI: {e}")
        return full_text[:150] + "..."

def fetch_article_details(link: str):
    """دریافت تصویر، متن کامل و ساخت خلاصه از صفحه اختصاصی خبر"""
    try:
        res = requests.get(link, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return None, None, None, 1
            
        soup = BeautifulSoup(res.content, "html.parser")
        
        # ۱. استخراج تصویر اصلی
        og_image = soup.find("meta", property="og:image")
        image_url = og_image["content"] if og_image and og_image.get("content") else None
        
        # ۲. استخراج متن کامل خبر
        story_div = soup.find("div", class_="story")
        full_text = ""
        if story_div:
            paragraphs = story_div.find_all("p")
            full_text = "\n".join([p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)])
        
        if not full_text:
            return image_url, None, None, 1
            
        # ۳. ساخت خلاصه و زمان مطالعه
        summary = summarize_with_ai(full_text)
        reading_time = get_reading_time(full_text)
        
        return image_url, full_text, summary, reading_time
    except Exception as e:
        print(f"⚠️ خطا در استخراج جزئیات خبر ({link}): {e}")
        return None, None, None, 1

def sync_news_to_supabase():
    print(f"\n[{time.strftime('%H:%M:%S')}] در حال بررسی آخرین اخبار تسنیم...")
    
    try:
        response = requests.get(URL, headers=HEADERS, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        articles = soup.find_all("article")
        new_count = 0

        for article in articles:
            a_tag = article.find("a")
            if not a_tag or "href" not in a_tag.attrs:
                continue

            href = a_tag["href"]
            link = href if href.startswith("http") else "https://www.tasnimnews.ir" + href

            title_el = article.find("h2") or article.find("h3") or a_tag
            title = title_el.get_text(strip=True)

            if not title or len(title) < 5:
                continue

            news_id = link.rstrip("/").split("/")[-1]
            
            time_el = article.find("time") or article.find("span", class_="time")
            published = time_el.get_text(strip=True) if time_el else "امروز"

            # ۳. بررسی تکراری نبودن و ثبت در Supabase
            try:
                existing = supabase.table("news").select("news_id").eq("news_id", news_id).execute()
                
                if not existing.data:
                    # دریافت جزئیات، عکس و خلاصه هوشمند
                    print(f"🔎 در حال دریافت محتوای غنی شده: {title[:35]}...")
                    image_url, full_text, summary, reading_time = fetch_article_details(link)

                    data = {
                        "news_id": news_id,
                        "title": title,
                        "link": link,
                        "published": published,
                        "image_url": image_url,
                        "summary": summary,
                        "full_text": full_text,
                        "reading_time": reading_time
                    }
                    
                    supabase.table("news").insert(data).execute()
                    new_count += 1
                    print(f"  🚀 [ارسال غنی‌سازی شده به پارتیم شو] {title}")
            except Exception as db_err:
                print(f"❌ خطا در ثبت خبر در Supabase: {db_err}")

        if new_count > 0:
            print(f"✓ تعداد {new_count} خبر جدید با عکس و خلاصه AI به اپلیکیشن ارسال شد.")
        else:
            print("✓ خبر جدیدی یافت نشد.")

    except Exception as e:
        print(f"❌ خطا در دریافت اخبار از تسنیم: {e}")

if __name__ == "__main__":
    print("🤖 ربات هوشمند اخبار پارتیم شو فعال شد (بررسی هر ۵ دقیقه)...")
    while True:
        sync_news_to_supabase()
        time.sleep(300)