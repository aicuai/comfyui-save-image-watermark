from .local_save_node import LocalSaveNode
from .watermark_node import LocalSaveImageWithWatermark, ExtractInvisibleWatermark

NODE_CLASS_MAPPINGS = {
    "Local Save": LocalSaveNode,
    "LocalSaveImageWithWatermark": LocalSaveImageWithWatermark,
    "ExtractInvisibleWatermark": ExtractInvisibleWatermark,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Local Save": "Local Save Image",
    "LocalSaveImageWithWatermark": "Save Image (Watermark) 💧",
    "ExtractInvisibleWatermark": "Extract Hidden Watermark 🔍",
}

WEB_DIRECTORY = "./js"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]