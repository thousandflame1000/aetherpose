AetherPose Windows 預覽版

1. 完整解壓縮 ZIP 到一般資料夾；請勿直接在壓縮檔內執行。
2. 雙擊 AetherPose.exe，等待操作網頁開啟。
3. 在「影像＋IMU 動作捕捉」按「開啟影像骨架」。請讓一人全身入鏡。
4. 用完按啟動器的「停止追蹤」，或關閉啟動器；相機與本次服務會停止。

基本相機追蹤不需安裝 Python、Rust、Arduino、SMPL 或 GlobalPose。
程式不會自動開啟相機、不會自動燒錄韌體。基本模式使用自行建構的通用人體，
比例是顯示用近似值，不能當作個人身體尺寸或真人精度驗證。

IMU 是選用的。若已有追蹤器，可在網頁指派部位並完成身體校正。
GlobalPose 為進階研究功能，仍需另外準備其 Python 3.8 環境、六個指定 IMU
與合法取得的 SMPL 檔案；本 ZIP 不包含受限人體模型或研究權重。
選用 SMPL .npz 時，可按啟動器的「匯入已授權 SMPL 人體」記住檔案位置。

設定與記錄：%LOCALAPPDATA%\AetherPose
網頁：http://127.0.0.1:18080/
若已有另一個版本占用 9009、9010 或 18080，請先停止另一個版本；本程式不會
強制關閉其他程式。記錄可透過啟動器的「開啟記錄資料夾」查看。

韌體燒錄與磁力計工具需要原始碼／Arduino 工具鏈，未包含在基本可攜版。
版本為未簽章預覽版。若 Windows 顯示來源警告，請核對下載來源和 SHA-256；
本說明不要求你關閉 SmartScreen、防毒軟體或其他安全防護。

原始碼、進階安裝與更新：https://github.com/thousandflame1000/aetherpose
第三方來源與授權請見 THIRD_PARTY_NOTICES.md 及 licenses 資料夾。
