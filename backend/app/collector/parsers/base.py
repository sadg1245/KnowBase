"""KnowBase 采集器流水线中所有文档解析器的抽象基类。"""

from abc import ABC, abstractmethod
from typing import Any


class BaseParser(ABC):
    """所有特定文件类型解析器必须继承的基类解析器。

    每个解析器负责从磁盘读取文件并返回文档块列表。
    一个块是包含两个键的字典：

        {
            "content": str,          # 块的文本内容
            "metadata": {
                "page_num": int,     # 页码 / 幻灯片 / 章节编号（从 1 开始）
                "heading": str,      # 可选——最近的标题或章节名
                "source_file": str,  # 文件名（非完整路径）
            }
        }
    """

    @abstractmethod
    def parse(self, file_path: str) -> list[dict[str, Any]]:
        """解析 *file_path* 并返回文档块字典列表。

        参数
        ----------
        file_path : str
            要解析的文件的绝对或相对路径。

        返回
        -------
        list[dict]
            每个元素为 ``{"content": str, "metadata": dict}``。

        抛出
        ------
        FileNotFoundError
            如果 *file_path* 不存在。
        PermissionError
            如果进程缺乏读取权限。
        ValueError
            如果文件损坏或无法读取。
        """
        ...
