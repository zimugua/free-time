"""
用户信息工具
从 data 包读取用户数据，用于预订时使用
"""
from typing import Dict

from .base import Tool
from data.users import MOCK_USERS


class GetUserInfoTool(Tool):
    """获取当前用户的姓名、联系方式和常住地址（Mock）"""

    def __init__(self):
        super().__init__("get_user_info")

    def run(self, user_name: str = "") -> Dict:
        """
        :param user_name: 可选，用户自报的姓名（如"我叫小张"）
        :return: 用户信息字典，包含 name、phone、address
        """
        if user_name and user_name.strip():
            name = user_name.strip()
            # Mock 手机号：根据姓名生成一个固定映射
            phone_hash = hash(name) % 9000 + 1000
            return {
                "name": name,
                "phone": f"138****{phone_hash}",
                "address": "朝阳区望京西园四区",
                "message": f"✅ 已识别用户：{name}（{phone_hash}），地址：朝阳区望京西园四区",
            }
        user = MOCK_USERS["default"]
        return {
            "name": user["name"],
            "phone": user["phone"],
            "address": user.get("address", "朝阳区望京西园四区"),
            "message": f"✅ 已识别用户：{user['name']}（{user['phone']}），地址：{user.get('address', '朝阳区望京西园四区')}",
        }
