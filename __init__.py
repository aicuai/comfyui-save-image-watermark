from .local_save_node import LocalSaveNode

NODE_CLASS_MAPPINGS = {
    "Local Save": LocalSaveNode
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Local Save": "Local Save Image"
}

WEB_DIRECTORY = "./js"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]