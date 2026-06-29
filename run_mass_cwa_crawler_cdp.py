import os
import time
import pandas as pd
from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta

# ==================== 設定區 ====================
CSV_FILE = "整合後_完整測站資料_正規化.csv"
# ===============================================

def run_mass_cwa_crawler_cdp():
    # 讀取 GitHub Secrets 傳進來的環境變數
    cwa_user = os.environ.get("CWA_USERNAME")
    cwa_pass = os.environ.get("CWA_PASSWORD")
    cwa_cookie_str = os.environ.get("CWA_COOKIE") # 👈 讀取關鍵的 Cookie
    
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
        context = browser.new_context(
            accept_downloads=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="zh-TW"
        )
        page = context.new_page()
        page.set_default_timeout(30000) 
        page.on("dialog", lambda dialog: dialog.dismiss())

        login_url = "https://agr.cwa.gov.tw/account/login"
        target_url = "https://agr.cwa.gov.tw/history/station_day"
        
        # ==================== 🔥 核心修正：Cookie 注入機制 🔥 ====================
        is_logged_in = False
        
        if cwa_cookie_str and cwa_cookie_str.strip():
            print("🍪 偵測到 CWA_COOKIE，正在進行 Cookie 注入免密登入...")
            try:
                cookie_list = []
                # 解析標準的 name1=value1; name2=value2 格式
                for item in cwa_cookie_str.split(";"):
                    item = item.strip()
                    if "=" in item:
                        k, v = item.split("=", 1)
                        cookie_list.append({
                            "name": k,
                            "value": v,
                            "domain": "agr.cwa.gov.tw",
                            "path": "/"
                        })
                context.add_cookies(cookie_list)
                print("✅ Cookie 注入成功！直接跳過登入步驟。")
                is_logged_in = True
            except Exception as ce:
                print(f"⚠️ Cookie 解析注入失敗: {ce}，將嘗試常規帳密登入。")
        
        # 如果沒提供 Cookie 或注入失敗，才走原本的帳密登入（當作備援機制）
        if not is_logged_in:
            if not cwa_user or not cwa_pass:
                print("❌ 找不到帳號密碼，且無可用 Cookie，爬蟲終止！")
                return
            print("🔑 未偵測到有效 Cookie，改走常規帳密登入頁面...")
            try:
                page.goto(login_url, wait_until="networkidle")
                page.locator('input[name="account"]').fill(cwa_user)
                page.locator('input[name="password"]').fill(cwa_pass)
                page.wait_for_timeout(500)
                page.locator('input[name="password"]').press("Enter")
                page.wait_for_timeout(5000)
            except Exception as e:
                print(f"❌ 常規登入控制發生異常: {e}")
                return
        # =======================================================================
        
        print("🚀 前往目標數據頁面...")
        page.goto(target_url, wait_until="networkidle")
        page.wait_for_timeout(3000) 
        
        # 截張圖確認此時進入數據頁面的狀態（是否成功解鎖權限）
        page.screenshot(path="target_page_status.png")
        
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

            # 下拉選單操作
            try:
                page.locator("select").nth(0).select_option(label=st_type, timeout=4000)
                page.wait_for_timeout(500)
                
                page.locator("select").nth(1).select_option(label=st_region, timeout=4000)
                page.wait_for_timeout(2500) 
                
                page.locator("select").nth(2).select_option(value=st_code, timeout=4000)
                page.wait_for_timeout(1000)
                
            except Exception as e:
                print(f"   ❌ 選單選取失敗！正在啟動天眼診斷機制...")
                try:
                    current_options = page.locator("select").nth(0).locator("option").all_inner_texts()
                    print(f"   🔍 [診斷結果] 目前網頁「站別選單」中實際存在的選項有：{current_options}")
                    print(f"   🔍 [診斷結果] 我們剛才試圖尋找的選項是：'{st_type}'")
                except Exception as diag_err:
                    print(f"   🔍 [診斷結果] 無法獲取選單內容: {diag_err}")
                
                print(f"   ⚠️ 無法選取 {st_name} ({st_code})，直接跳過此測站！")
                continue 
            
            if page.get_by_text("此站無觀測要素").count() > 0:
                print(f"   ⚠️ {st_name} 無觀測要素，直接跳過此測站。")
                page.goto(target_url, wait_until="networkidle")
                continue

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
