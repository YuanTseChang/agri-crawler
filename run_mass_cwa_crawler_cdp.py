import os
import time
import pandas as pd
from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta

# ==================== 設定區 ====================
CSV_FILE = "整合後_完整測站資料_正規化.csv"
# ===============================================

def run_mass_cwa_crawler_cdp():
    # 讀取 GitHub Secrets 傳進來的帳密
    cwa_user = os.environ.get("CWA_USERNAME")
    cwa_pass = os.environ.get("CWA_PASSWORD")
    
    if not cwa_user or not cwa_pass:
        print("❌ 找不到帳號或密碼環境變數，請確認 GitHub Secrets 設定！")
        return
        
    # 讀取 CSV
    df_stations = pd.read_csv(CSV_FILE, encoding="utf-8-sig")
    df_stations['資料起始日期'] = pd.to_datetime(df_stations['資料起始日期'], errors='coerce')
    df_stations['撤站日期'] = pd.to_datetime(df_stations['撤站日期'], errors='coerce')
    
    total_stations = len(df_stations)
    yesterday = datetime.now() - timedelta(days=1)
    
    print(f"🎯 讀取成功！即將開始依據各測站存續期間下載資料...")

    print("🔗 正在啟動 Chromium 瀏覽器...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        # 設定標準台灣語系與常用 User-Agent，最大程度偽裝成真實瀏覽器
        context = browser.new_context(
            accept_downloads=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="zh-TW"
        )
        page = context.new_page()
        page.set_default_timeout(30000) 
        page.on("dialog", lambda dialog: dialog.dismiss())

        # ==================== 🔐 網頁模擬登入與嚴格驗證區塊 🔐 ====================
        login_url = "https://agr.cwa.gov.tw/account/login"
        target_url = "https://agr.cwa.gov.tw/history/station_day"
        
        print("🔑 正在連線至登入頁面...")
        try:
            page.goto(login_url, wait_until="networkidle")
            
            print("✍️ 填寫帳號與密碼...")
            page.locator('input[name="account"]').fill(cwa_user)
            page.locator('input[name="password"]').fill(cwa_pass)
            page.wait_for_timeout(500)
            
            print("👆 發送登入請求 (按下 Enter)...")
            page.locator('input[name="password"]').press("Enter")
            
            # 給予 5 秒讓非同步 AJAX 完成驗證與登入 Cookie 配發
            page.wait_for_timeout(5000)
            
            # 存下登入當下的截圖
            page.screenshot(path="login_result.png")
            print("📸 已擷取登入結果截圖並儲存為 login_result.png")
            
            print(f"ℹ️ 登入判定點 - 當前網頁網址: {page.url}")
            if "error_message" in page.url or "login" in page.url:
                print("⚠️ 警告：網址仍停留在登入頁面，登入【確定失敗】！")
                print("👉 請檢查：1. GitHub Secrets 的帳密是否打錯。 2. 氣象署防火牆封鎖了海外機房 IP。")
            else:
                print("✅ 網址已成功跳轉，可能已順利登入！")
                
        except Exception as e:
            print(f"❌ 登入自動化控制發生異常: {e}")
            return
        
        print("🚀 前往目標數據頁面...")
        page.goto(target_url, wait_until="networkidle")
        page.wait_for_timeout(3000) 
        # ===================================================================
        
        for index, row in df_stations.iterrows():
            st_code = str(row['站號']).strip()
            st_name = str(row['站名']).strip()
            st_region = str(row['區域']).strip()
            st_type = str(row['站別']).strip()
            
            start_date_limit = row['資料起始日期'] if pd.notnull(row['資料起始日期']) else datetime(2019, 1, 1)
            end_date_limit = row['撤站日期'] if pd.notnull(row['撤站日期']) else yesterday
            
            output_dir = os.path.join("daily", f"{st_code}_{st_name}")
            os.makedirs(output_dir, exist_ok=True)
            
            print(f"\n🏭 [{index+1}/{total_stations}] {st_name} ({st_code}) | 區間: {start_date_limit.strftime('%Y-%m-%d')} ~ {end_date_limit.strftime('%Y-%m-%d')}")
            
            if target_url not in page.url:
                page.goto(target_url, wait_until="networkidle")

            # 🔥 下拉選單操作（內建全自動診斷機制）
            try:
                # 1. 選擇站別
                page.locator("select").nth(0).select_option(label=st_type, timeout=3000)
                page.wait_for_timeout(500)
                
                # 2. 選擇區域
                page.locator("select").nth(1).select_option(label=st_region, timeout=3000)
                page.wait_for_timeout(2000) 
                
                # 3. 選擇測站
                page.locator("select").nth(2).select_option(value=st_code, timeout=3000)
                page.wait_for_timeout(1000)
                
            except Exception as e:
                print(f"   ❌ 選單選取失敗！正在啟動天眼診斷機制...")
                try:
                    # 抓出當前網頁上第一個選單（站別）到底出現了哪些選項
                    current_options = page.locator("select").nth(0).locator("option").all_inner_texts()
                    print(f"   🔍 [診斷結果] 目前網頁「站別選單」中實際存在的選項有：{current_options}")
                    print(f"   🔍 [診斷結果] 我們剛才試圖尋找的選項是：'{st_type}'")
                    print(f"   🔍 [診斷結果] 當前瀏覽器實際停留在網址：{page.url}")
                except Exception as diag_err:
                    print(f"   🔍 [診斷結果] 無法獲取選單內容: {diag_err}")
                
                print(f"   ⚠️ 無法選取 {st_name} ({st_code})，直接跳過此測站！")
                continue 
            
            if page.get_by_text("此站無觀測要素").count() > 0:
                print(f"   ⚠️ {st_name} 無觀測要素，直接跳過此測站。")
                page.goto(target_url, wait_until="networkidle")
                continue

            # --- 年度迴圈 ---
            for year in range(start_date_limit.year, end_date_limit.year + 1):
                year_start = max(start_date_limit, datetime(year, 1, 1))
                year_end = min(end_date_limit, datetime(year, 12, 31))
                
                start_str = year_start.strftime("%Y-%m-%d")
                end_str = year_end.strftime("%Y-%m-%d")
                target_path = os.path.join(output_dir, f"{year}.csv")
                
                if os.path.exists(target_path) and os.path.getsize(target_path) > 500:
                    print(f"   ⏭️  {year} 年已存在，跳過。")
                    continue
                
                print(f"   📅 下載 {year} ({start_str} ~ {end_str}) ...")
                
                try:
                    items_select = page.locator("select").nth(3)
                    items_select.evaluate("select => { for (let opt of select.options) opt.selected = true; select.dispatchEvent(new Event('change', { bubbles: true })); }")
                    
                    page.evaluate(f"""() => {{
                        const inputs = Array.from(document.querySelectorAll('input')).filter(i => i.value.match(/^\d{{4}}-\d{{2}}-\d{{2}}$/));
                        if(inputs.length >= 2) {{
                            inputs[0].value = '{start_str}'; inputs[0].dispatchEvent(new Event('change', {{bubbles:true}}));
                            inputs[1].value = '{end_str}'; inputs[1].dispatchEvent(new Event('change', {{bubbles:true}}));
                        }}
                    }}""")
                    
                    try: page.locator("input[type='radio']").last.click()
                    except: page.get_by_text("依觀測時間排序").click()
                    
                    download_btn = page.locator("button:has-text('下載檔案')")
                    if download_btn.count() == 0: download_btn = page.locator(".btn-success, button").last
                    
                    download_btn.wait_for(state="visible", timeout=3000)
                    
                    with page.expect_download(timeout=5000) as download_info:
                        download_btn.click()
                        page.wait_for_timeout(800) 
                        if "create_report" in page.url:
                            raise Exception("網頁進入空白報告頁，下載失敗")
 
                    download_info.value.save_as(target_path)
                    print(f"   ✨ {year} 下載成功！")
                    
                except Exception as e:
                    print(f"   ⚠️ {year} 年下載失敗或跳轉白頁，跳過...")
                    page.goto(target_url, wait_until="networkidle")
                    page.locator("select").nth(0).select_option(label=st_type)
                    page.locator("select").nth(1).select_option(label=st_region)
                    page.locator("select").nth(2).select_option(value=st_code)
                    page.wait_for_timeout(1000)
                    continue 

        print("\n🎉 所有測站全部完成！")

if __name__ == "__main__":
    run_mass_cwa_crawler_cdp()
