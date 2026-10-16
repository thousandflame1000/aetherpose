# 原始碼審閱包

## 建立與核對

在專案根目錄執行，輸出路徑必須尚不存在：

```powershell
..\.venv\Scripts\python.exe tools\package_submission.py build --output releases\aetherpose-source-review-new.zip
..\.venv\Scripts\python.exe tools\package_submission.py verify releases\aetherpose-source-review-new.zip
```

如果使用專案內的虛擬環境，改用 `.\.venv\Scripts\python.exe`。工具本身只使用 Python 標準函式庫，接收者也可用既有 Python 執行驗證。成功會回傳 `verified: true`、檔案數及未壓縮大小；失敗會以非零退出碼說明原因，不覆蓋舊包。

包內 `aetherpose/SUBMISSION_MANIFEST.json` 列出每個檔案的大小與 SHA-256。驗證器不需解壓就能檢查逐檔內容，會拒絕額外或遺漏的檔案、雜湊不符、重複路徑、Windows 保留名稱、路徑穿越與來源政策外的項目。雜湊不是數位簽章，也不證明內容作者、授權或實體驗收。

## 範圍

| 納入 | 排除 |
|---|---|
| Rust 與韌體原始碼、Fusion 版本及授權檔 | 編譯輸出、Arduino 工具與快取 |
| Python 服務、工具、套件清單 | Python 虛擬環境及快取 |
| 瀏覽器程式與既有展示素材及來源說明 | 模型、權重、資料集及使用者輸入資產 |
| 測試、操作文件、報告審閱文字 | 個人設定、外部路徑、原始實驗及錄製紀錄 |
| 根目錄啟停及安裝腳本、外部路徑範例 | 本機 `.cargo`／IDE 設定、歷史備份壓縮檔 |

這是目前工作樹的原始碼快照，包含符合政策的未提交程式；不是只匯出 Git 已追蹤檔案。工具依目錄與副檔名明確選取，拒絕跟隨符號連結或 junction，以避免複製專案外內容。檔案內容的來源及提交範圍仍須依 `EXTERNAL_DEPENDENCIES.md` 與素材說明審閱。

二進位展示素材與文件截圖另採明確檔名清單；任意放入的 GLB、圖片或模型二進位檔不會被自動納入。新增正式素材時，需同步更新工具的 `STATIC_FILES`、來源說明與檔案引用測試。

`config.json` 不納入；第一次啟動時後端使用預設設定並建立本機狀態。`external_paths.json` 也不納入，接收者須依範例填入自己取得的外部資源。包內不含可直接執行的後端二進位檔，也不包含正式 Word 報告、簡報與真人展示影片；這些是另外的交付物。

## 接收者操作

1. 在解壓前核對壓縮包，再解壓到新的資料夾；不要覆蓋舊工作樹。
2. 閱讀 `PACKAGE_NOTES.md`、`HANDOFF.md` 與 `EXTERNAL_DEPENDENCIES.md`。
3. 準備文件列出的 Python、Rust 及外部資源，執行 `setup.ps1`。單純安裝不會自動燒錄，韌體上傳另使用明確選項。
4. 填寫自己的外部路徑，執行 `frontend/external_paths.py` 確認，再用 `run.ps1` 啟動。
5. 依 `docs/experiments.md` 記錄來源與環境。沒有六顆實體輸入的展示只作軟體流程驗證。

安裝需要套件及編譯工具；提交包不代表可離線安裝全部依賴。另需確認接收者有權取得並使用相應模型、資料及權重。

## 驗證層次

壓縮包通過驗證，只證明其結構與 manifest 相符。從解壓副本執行程式引用檢查，可進一步檢查檔案是否漏帶。沿用開發機的 Python、Rust 與套件快取進行測試，仍不是另一台乾淨電腦的完整安裝證據；後者屬畢設計畫的 G2，須另外記錄並驗收。

程式變更後應使用新檔名重新打包，不修改已保留的審閱包。驗收紀錄與最終交付清單必須寫出實際對應的包名及測試環境，避免以舊包代表新程式。

## 本次審閱包驗證紀錄

軟體限定範圍的最新快照：`aetherpose-software-review-20261015-v7.zip`，187 個 payload 檔案、未壓縮合計 13,105,268 bytes，manifest 驗證通過。SHA-256 為 `b56d40d61df65b8abd3e02c2641b969fc6b684dc1435597e33068104a27ecfdc`。打包前完整軟體／Live 驗收退出碼 0（兩尺寸各 768 項瀏覽器檢查，模擬深蹲固定 20 秒得分 5）。解壓副本另通過 11 項整合、3 項環境預檢及 768 項瀏覽器檢查。原始測試輸出與範圍、未執行測試、效能限制保存在 `releases/package-validation-software-20261015-v7.json`。本版本不宣稱效能穩定目標已達成，也不宣稱乾淨機器安裝；本段為打包後補記，ZIP 保持凍結。

2026 年 10 月 15 日再增 `aetherpose-source-review-20261015-v6.zip`：184 個 payload 檔案、未壓縮合計 13,085,325 bytes，包含校正開局門檻、遠端校正停止計分、試次分析工具與標註規範。SHA-256 為 `f8541401118d79c00fbe1492f82f4de45707ee2dd97cf6a68ea20858b0a20557`。完整 `-Live` 退出碼 0；打包後解壓副本通過 11 項整合、6 項試次分析及 766 項瀏覽器檢查，結構與 manifest 驗證通過。完整驗收中的符號連結測試仍有一項環境限制跳過。詳細原始輸出保存在 `releases/package-validation-20261015-v6.json`。沿用開發機環境，實體與乾淨機驗收仍待完成；本段為打包後補記，ZIP 保持凍結。

2026 年 10 月 15 日新增 `aetherpose-source-review-20261015-v5.zip`：180 個 payload 檔案、未壓縮合計 13,058,355 bytes，結構與 SHA-256 manifest 驗證通過。壓縮包 SHA-256 為 `0157406dcf4f06f8d5ef76923721892dd67b8da52faac578d01b42189688d5da`。此版本包含固定視窗批次修正與程序 CPU 延遲策略。打包前完整 `-Live` 驗收退出碼為 0；解壓副本另通過 11 項整合與 4 項 CPU 策略測試，沿用開發機 Python，仍不代表乾淨機器安裝。摘要保存在 `releases/package-validation-20261015-v5.json`。本段為打包後補記，壓縮包保持凍結。

2026 年 10 月 14 日保留的審閱快照為 `aetherpose-source-review-20261014-v4.zip`，ZIP 大小 10,798,086 bytes；176 個 payload 檔案加一份 manifest，未壓縮 payload 合計 13,024,991 bytes。SHA-256 為 `4d738c24e023c3ade09223d858a133583ebbf4c3131e9491f0dda7084c13869c`。

v3 解壓副本完成 10 項整合、757 項瀏覽器及 54 項離線 Rust 測試；v4 更新提交工具的檔案連結檢查後，再解壓完成整合及提交工具測試。v4 的 119 個執行程式與素材檔案經 manifest 比對與 v3 一致。提交工具測試實際為 5 通過、1 跳過，跳過原因是本機無法建立測試符號連結；不能把它寫成全數實際執行通過。

詳細記錄保存在開發機 `releases/package-validation-20261014-v4.json`。這是來源快照與結構驗證，未包含本段後續補上的驗收敘述，也不宣稱包含之後的程式變更。原始碼快照已凍結；後續修改需另建新版本。
