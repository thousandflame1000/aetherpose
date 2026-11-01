# 素材來源與權利核對

核對日期：2026-10-18。結論：不能主張所有素材著作權均屬本團隊。以下區分專案內生成、第三方開放素材及受限外部模型；原始碼存在只能支持製作來源，不能取代成員、學校或委託契約的權利歸屬文件。

| 素材 | 來源證據 | 可以如何說明 |
|---|---|---|
| 十個訓練道具 GLB | `tools/make_scene_props.py`、`webui/assets/props/`；整合測試比對產物與生成器 | 本專案生成的道具。現有檔頭與素材 README 已宣告 CC0，不宜主張排他使用權；本次未改動授權 |
| 訓練場與場景材質 | `webui/environment.js` 以幾何與 canvas 生成，未載入外部貼圖檔 | 可說明為專案內以程式建構的場景；不據此確認最終契約歸屬 |
| 遊戲提示音 | `webui/games.js` 的 Web Audio oscillator | 專案內合成提示音，未發現另行載入的音樂／音效檔 |
| RobotExpressive 機器人 | Tomás Laulhé / Quaternius，Don McCurdy 修改；Three.js r128 上游 README | 第三方 CC0 素材，非我們原創，未轉成我們專屬所有 |
| Lantern 燈籠 | Microsoft / sbtron，Frank Galligan；Khronos 上游文件 | 第三方 CC0 素材，非我們原創 |
| 3D 人體形狀 | 外部 SMPL 模型與其衍生網格；`EXTERNAL_DEPENDENCIES.md` | 不能聲稱人體模型由我們製作或所有。官方模型授權有非商業用途與散布限制，實際檔案須核對取得時的授權 |
| 系統截圖與投影片中的畫面 | 專案實際頁面截圖，可能同時出現機器人及 SMPL 人體 | 截圖由我們截取，不代表截圖內的第三方素材著作權也屬我們 |
| 字型 | CSS 使用系統字型；簡報指定 Microsoft JhengHei | 不主張字型所有權，使用與散布字型檔須依字型授權；目前未因本次報告加入字型檔 |
| Three.js 與控制器／載入器 | `webui/vendor/three/LICENSE` | 第三方 MIT 程式庫，保留版權與授權聲明；不是我們原創 |
| Fusion AHRS | 韌體內第三方 `Fusion/LICENSE.md` | 第三方 MIT 程式庫，保留聲明 |
| TransPose、預訓練權重、DIP-IMU | `EXTERNAL_DEPENDENCIES.md`，外部檔案路徑 | 第三方方法與資料，不是我們的模型或資料集。TransPose 程式碼 GPL-3.0，權重與資料授權分別確認，不能由程式授權直接推定 |
| PCB 預覽與工程資料 | 專案生成，但使用 Espressif／KiCad 上游封裝與廠商資料表 | 可說明電路整合與版圖設計工作，不能主張封裝庫、資料表或廠商圖像由我們原創 |

## 報告可直接使用的文字

> 本專題自行實作系統整合、遊戲互動與回合管理功能，並以程式建構訓練場及訓練道具。機器人與燈籠使用第三方 CC0 素材，人體姿態重建採用外部 TransPose 與 SMPL；相關作者與授權另行揭露。本專題不主張全部素材均為原創或具有排他所有權。

## 核對依據

- 機器人原作者與 CC0：[Three.js r128 RobotExpressive README](https://raw.githubusercontent.com/mrdoob/three.js/r128/examples/models/gltf/RobotExpressive/README.md)
- 燈籠作者與 CC0：[Khronos Lantern README](https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models/Lantern/README.md)
- CC0 允許複製、修改與散布，不將第三方作品變成本團隊排他所有：[Creative Commons CC0 說明](https://creativecommons.org/publicdomain/zero/1.0/)
- [SMPL 官方模型授權](https://smpl.is.tue.mpg.de/modellicense.html)：列有原權利人、用途及散布限制。僅憑本機有檔案，無法確認使用者是否已取得適用授權
- [TransPose 上游 LICENSE](https://raw.githubusercontent.com/Xinyu-Yi/TransPose/main/LICENSE)
- [Three.js r128 MIT LICENSE](https://raw.githubusercontent.com/mrdoob/three.js/r128/LICENSE)
- 本機文件：`webui/assets/README.md`、`EXTERNAL_DEPENDENCIES.md`、`hardware/custom-tracker/SOURCES.md`
- GLB 本體與上游位元組比對另記 `docs/asset-provenance-check.json`，其結果僅驗證來源一致性，不是權利移轉證明

## 尚不能確認的部分

未看到團隊成員間的著作權約定、學校專題權利規範或委託契約，因此無法從程式庫確認所有專案內原創表達最終都歸屬「我們」這個組織。也沒有以本次檢查補辦或推定任何 SMPL／資料集授權。此次未移除第三方聲明、改寫作者或重新授權既有素材。
