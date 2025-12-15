import torch
import numpy as np
from PIL import Image
import base64
from io import BytesIO
from datetime import datetime
from server import PromptServer

class LocalSaveNode:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "images": ("IMAGE",),
                "prefix": ("STRING", {"default": "generated"}),
                "file_format": (["PNG", "JPEG"], {"default": "PNG"}),
            }
        }
    
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "process_images"
    CATEGORY = "image"
    OUTPUT_NODE = True

    def process_images(self, images, prefix, file_format):
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_data_list = []
            
            # バッチ内の各画像を処理
            for i in range(len(images)):
                # 画像データの変換
                img_tensor = images[i]
                img_numpy = 255. * img_tensor.cpu().numpy()
                img = Image.fromarray(np.clip(img_numpy, 0, 255).astype(np.uint8))
                
                # シンプルなファイル名の生成
                filename = f"{prefix}_{timestamp}_{i+1:03d}"
                full_filename = f"{filename}.{file_format.lower()}"
                
                # 画像をbase64エンコード
                buffered = BytesIO()
                if file_format == "PNG":
                    img.save(buffered, format="PNG")
                else:
                    img.save(buffered, format="JPEG", quality=95)
                img_str = base64.b64encode(buffered.getvalue()).decode()
                
                # データをリストに追加
                image_data_list.append({
                    "filename": full_filename,
                    "data": img_str,
                    "format": file_format.lower()
                })
            
            # クライアントにデータを送信
            PromptServer.instance.send_sync("local_save_data", {
                "images": image_data_list
            })
            
            return (images,)
            
        except Exception as e:
            error_msg = f"Error processing images: {str(e)}"
            PromptServer.instance.send_sync("local_save_error", {
                "message": error_msg
            })
            raise Exception(error_msg)