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

    print("🔗 正在連線至真實 Chrome (Port 9222)...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(30000) 
        page.on("dialog", lambda dialog: dialog.dismiss())

        # ==================== 新增：自動登入區塊 ====================
        print("🔐 正在執行自動登入...")
        login_url = "https://agr.cwa.gov.tw/account/login"
        
        # 1. 前往登入頁，並確保網路載入完畢
        page.goto(login_url, wait_until="networkidle")
        
        # 2. 填入帳密
        page.locator('input[name="account"]').fill(cwa_user)
        page.locator('input[name="password"]').fill(cwa_pass)
        
        # 3. 點擊登入，並同時等待網頁跳轉 (這可以確保 Cookie 成功寫入)
        page.locator('#login').click()
        
        print("⏳ 等待登入跳轉中...")
        # 強化等待：等 5 秒讓網頁處理登入與 Session 寫入
        page.wait_for_timeout(5000) 
        
        # 4. 正式前往目標爬蟲頁面
        target_url = "https://agr.cwa.gov.tw/history/station_day"
        page.goto(target_url, wait_until="networkidle")
        page.wait_for_timeout(2000) # 給選單元件額外 2 秒的渲染時間
        
        print("✅ 登入步驟完成，準備開始爬蟲！")
        # ==========================================================

        target_url = "https://agr.cwa.gov.tw/history/station_day"
        
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
            try:
                # 下拉選單操作 (加入 timeout=3000，找不到選項只等 3 秒就放棄，不浪費 30 秒)
                page.locator("select").nth(0).select_option(label=st_type, timeout=3000)
                page.wait_for_timeout(300)
                page.locator("select").nth(1).select_option(label=st_region, timeout=3000)
                page.wait_for_timeout(300)
                page.locator("select").nth(2).select_option(value=st_code, timeout=3000)
                page.wait_for_timeout(1000)
            except Exception as e:
                print(f"   ⚠️ 網頁選單中找不到 {st_name} ({st_code}) 的選項 (可能已下架)。直接跳過！")
                continue # 放棄這個測站，直接進入下一個測站的迴圈
            
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
