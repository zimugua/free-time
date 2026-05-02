"""
工具基类模块
"""


class Tool:
    """所有工具的抽象基类"""

    def __init__(self, name: str):
        self.name = name

    def run(self, **kwargs):
        raise NotImplementedError(f"Tool '{self.name}' must implement run()")

    def __repr__(self):
        return f"<Tool name={self.name}>"
