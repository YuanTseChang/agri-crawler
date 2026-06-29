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
        
    df_stations = pd.read_csv(CSV_FILE, encoding="utf-8-sig")
    df_stations['資料起始日期'] = pd.to_datetime(df_stations['資料起始日期'], errors='coerce')
    df_stations['撤站日期'] = pd.to_datetime(df_stations['撤站日期'], errors='coerce')
    
    total_stations = len(df_stations)
    yesterday = datetime.now() - timedelta(days=1)
    
    print(f"🎯 讀取成功！即將開始依據各測站存續期間下載資料...")

    print("🔗 正在連線至真實 Chrome...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        
        # 建議加上 User-Agent，降低被伺服器阻擋的機率
        context = browser.new_context(
            accept_downloads=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.set_default_timeout(30000) 
        page.on("dialog", lambda dialog: dialog.dismiss())

        # ==================== 修改：真實模擬 UI 登入區塊 ====================
        print("🔑 正在執行自動化登入程序...")
        login_url = "https://agr.cwa.gov.tw/account/login"
        
        try:
            page.goto(login_url, wait_until="networkidle")
            
            # 填寫帳號 (這裡使用廣泛支援的選取器，會尋找 name 為 email 或 account 的輸入框)
            # 若 CWA 網站的登入框有特定的 id，可改為 page.locator("#id名稱").fill(cwa_user)
            page.locator("input[type='email'], input[type='text']").first.fill(cwa_user)
            page.locator("input[type='password']").first.fill(cwa_pass)
            
            # 點擊登入按鈕
            page.locator("button[type='submit'], button:has-text('登入')").first.click()
            
            # 等待頁面跳轉 (成功登入後通常會跳轉回首頁或指定頁面)
            # 我們給予 10 秒的時間讓 Laravel 伺服器處理驗證並配發最新 Cookie
            page.wait_for_timeout(3000)
            print("✅ 登入請求已發送，準備前往目標頁面！")
            
        except Exception as e:
            print(f"❌ 登入過程發生錯誤: {e}")
            return
        
        # 登入完成後，前往目標爬蟲頁面
        target_url = "https://agr.cwa.gov.tw/history/station_day"
        print("🚀 前往目標數據頁面...")
        page.goto(target_url, wait_until="networkidle")
        page.wait_for_timeout(3000) 
        # ===================================================================
        
        # ... 後面的 for index, row in df_stations.iterrows(): 迴圈保持完全不變 ...
        for index, row in df_stations.iterrows():
            st_code = str(row['站號']).strip()
            # ... (保留你原本的所有測站處理邏輯) ...
        # ===================================================================
        
        for index, row in df_stations.iterrows():
            st_code = str(row['站號']).strip()
            st_name = str(row['站名']).strip()
            st_region = str(row['區域']).strip()
            st_type = str(row['站別']).strip()
            
            # --- 計算該測站起訖 ---
            start_date_limit = row['資料起始日期'] if pd.notnull(row['資料起始日期']) else datetime(2019, 1, 1)
            end_date_limit = row['撤站日期'] if pd.notnull(row['撤站日期']) else yesterday
            
            output_dir = os.path.join("daily", f"{st_code}_{st_name}")
            os.makedirs(output_dir, exist_ok=True)
            
            print(f"\n🏭 [{index+1}/{total_stations}] {st_name} ({st_code}) | 區間: {start_date_limit.strftime('%Y-%m-%d')} ~ {end_date_limit.strftime('%Y-%m-%d')}")
            
            # 確保在目標頁面
            if target_url not in page.url:
                page.goto(target_url, wait_until="networkidle")

            # 下拉選單操作
            # (修改後的程式碼)
            # --- 替換從這裡開始的下拉選單操作 ---
            try:
                # 1. 選擇站別 (Station Type)
                try:
                    page.locator("select").nth(0).select_option(label=st_type, timeout=3000)
                except:
                    raise Exception(f"選單找不到對應的「站別」: {st_type}")
                
                # 🔥 延長等待：給 GitHub 跨海連線緩衝
                page.wait_for_timeout(1500) 
                
                # 2. 選擇區域 (Region)
                try:
                    page.locator("select").nth(1).select_option(label=st_region, timeout=3000)
                except:
                    raise Exception(f"選單找不到對應的「區域」: {st_region}")
                
                # 🔥 延長等待：等待 AJAX 請求把該區域的測站名單拉回來
                page.wait_for_timeout(2000) 
                
                # 3. 選擇測站 (Station)
                try:
                    page.locator("select").nth(2).select_option(value=st_code, timeout=4000)
                except:
                    raise Exception(f"區域載入完成，但測站列表中沒有 {st_name} ({st_code})")
                
                page.wait_for_timeout(1000)
                
            except Exception as e:
                print(f"   ⚠️ {e}。直接跳過！")
                # 為了避免殘留錯誤的選單狀態，重新整理頁面
                page.goto(target_url, wait_until="networkidle") 
                continue # 放棄這個測站，直接進入下一個
            # ------------------------------------
            
            # --- 【新增檢查邏輯】 ---
            if page.get_by_text("此站無觀測要素").count() > 0:
                print(f"   ⚠️ {st_name} 無觀測要素，直接跳過此測站。")
                page.goto(target_url, wait_until="networkidle")
                continue
            # ----------------------

            # --- 年度迴圈 ---
            for year in range(start_date_limit.year, end_date_limit.year + 1):
                # 計算該年份的實際起訖 (不能超過測站的起始/撤站限制)
                year_start = max(start_date_limit, datetime(year, 1, 1))
                year_end = min(end_date_limit, datetime(year, 12, 31))
                
                start_str = year_start.strftime("%Y-%m-%d")
                end_str = year_end.strftime("%Y-%m-%d")
                target_path = os.path.join(output_dir, f"{year}.csv")
                
                # 斷點續傳
                if os.path.exists(target_path) and os.path.getsize(target_path) > 500:
                    print(f"   ⏭️  {year} 年已存在，跳過。")
                    continue
                
                print(f"   📅 下載 {year} ({start_str} ~ {end_str}) ...")
                
                try:
                    # 全選觀測要素
                    items_select = page.locator("select").nth(3)
                    items_select.evaluate("select => { for (let opt of select.options) opt.selected = true; select.dispatchEvent(new Event('change', { bubbles: true })); }")
                    
                    # 填入日期
                    page.evaluate(f"""() => {{
                        const inputs = Array.from(document.querySelectorAll('input')).filter(i => i.value.match(/^\d{{4}}-\d{{2}}-\d{{2}}$/));
                        if(inputs.length >= 2) {{
                            inputs[0].value = '{start_str}'; inputs[0].dispatchEvent(new Event('change', {{bubbles:true}}));
                            inputs[1].value = '{end_str}'; inputs[1].dispatchEvent(new Event('change', {{bubbles:true}}));
                        }}
                    }}""")
                    
                    # 點擊排序
                    try: page.locator("input[type='radio']").last.click()
                    except: page.get_by_text("依觀測時間排序").click()
                    
                    # 【核心關鍵】等待下載按鈕出現 (設定 3 秒超時，沒資料就跳出)
                    download_btn = page.locator("button:has-text('下載檔案')")
                    if download_btn.count() == 0: download_btn = page.locator(".btn-success, button").last
                    
                    # 只要 3 秒內按鈕無法使用，直接拋出錯誤跳過
                    download_btn.wait_for(state="visible", timeout=3000)
                    
                    with page.expect_download(timeout=5000) as download_info:
                        download_btn.click()
                            
                        # 額外偵測：如果點擊後網址變成了 create_report，代表下載失敗
                        page.wait_for_timeout(800) # 給網頁 0.8 秒反應
                        if "create_report" in page.url:
                            raise Exception("網頁進入空白報告頁，下載失敗")
 
                    download_info.value.save_as(target_path)
                    print(f"   ✨ {year} 下載成功！")
                    
                except Exception as e:
                    print(f"   ⚠️ {year} 年下載失敗或跳轉白頁，跳過...")
                    # 強制導航回目標頁，清除空白頁狀態
                    page.goto(target_url, wait_until="networkidle")
                    # 重新選取測站 (為了讓下一年的迴圈能正常執行)
                    page.locator("select").nth(0).select_option(label=st_type)
                    page.locator("select").nth(1).select_option(label=st_region)
                    page.locator("select").nth(2).select_option(value=st_code)
                    page.wait_for_timeout(1000)
                    continue # 進入下一個年份

        print("\n🎉 所有測站全部完成！")

if __name__ == "__main__":
    run_mass_cwa_crawler_cdp()
