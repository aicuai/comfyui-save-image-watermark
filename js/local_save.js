import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

app.registerExtension({
    name: "Comfy.LocalSave",
    async setup() {
        // Base64をBlobに変換するユーティリティ関数
        function base64ToBlob(base64, mimeType) {
            // Base64文字列をバイナリデータに変換
            const byteString = atob(base64);
            // バイナリデータをUint8Arrayに変換
            const ab = new ArrayBuffer(byteString.length);
            const ia = new Uint8Array(ab);
            for (let i = 0; i < byteString.length; i++) {
                ia[i] = byteString.charCodeAt(i);
            }
            // Blobを作成して返す
            return new Blob([ab], { type: mimeType });
        }

        // 画像データ受信時のハンドラー
        api.addEventListener("local_save_data", async ({ detail }) => {
            try {
                const { images } = detail;
                
                for (const imageData of images) {
                    const { filename, data, format } = imageData;
                    
                    // Base64データを直接Blobに変換
                    const blob = base64ToBlob(data, `image/${format}`);
                    
                    // ダウンロードリンクを作成
                    const downloadLink = document.createElement("a");
                    downloadLink.href = URL.createObjectURL(blob);
                    downloadLink.download = filename;
                    
                    // ダウンロードを実行
                    document.body.appendChild(downloadLink);
                    downloadLink.click();
                    document.body.removeChild(downloadLink);
                    URL.revokeObjectURL(downloadLink.href);
                }
                
            } catch (error) {
                // エラーメッセージを表示
                app.ui.dialog.show("Save Error", `Error downloading images: ${error.message}`);
            }
        });

        // エラーメッセージのハンドラー
        api.addEventListener("local_save_error", ({ detail }) => {
            app.ui.dialog.show("Save Error", detail.message);
        });
    }
});