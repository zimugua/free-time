"""
预订相关工具：活动门票预订 & 餐厅预订
预订时带入用户姓名和联系方式
"""
import random
from datetime import datetime
from typing import Dict

from .base import Tool


class BookActivityTool(Tool):
    """预订活动门票（Mock），以用户姓名和电话下单"""

    def __init__(self):
        super().__init__("book_activity")

    def run(
        self,
        activity_name: str,
        time: datetime,
        people: int,
        user_name: str = "",
        user_phone: str = "",
    ) -> Dict:
        """
        :param activity_name: 活动名称
        :param time: 活动时间
        :param people: 参与人数
        :param user_name: 下单人姓名
        :param user_phone: 下单人手机号
        :return: 预订结果
        """
        ticket_id = f"ACT{random.randint(10000, 99999)}"
        contact = f"（{user_name} {user_phone}）" if user_name else ""
        return {
            "success": True,
            "ticket_id": ticket_id,
            "activity": activity_name,
            "time": time.strftime("%Y-%m-%d %H:%M"),
            "people": people,
            "user_name": user_name,
            "user_phone": user_phone,
            "message": f"✅ 已预订【{activity_name}】门票 {people} 张，{time.strftime('%H:%M')} 场次，票号：{ticket_id} {contact}",
        }


class BookRestaurantTool(Tool):
    """预订餐厅座位（Mock），以用户姓名和电话下单"""

    def __init__(self):
        super().__init__("book_restaurant")

    def run(
        self,
        restaurant_name: str,
        time: datetime,
        people: int,
        special_request: str = "",
        user_name: str = "",
        user_phone: str = "",
    ) -> Dict:
        """
        :param restaurant_name: 餐厅名称
        :param time: 用餐时间
        :param people: 用餐人数
        :param special_request: 特殊需求
        :param user_name: 下单人姓名
        :param user_phone: 下单人手机号
        :return: 预订结果
        """
        booking_id = f"RES{random.randint(10000, 99999)}"
        contact = f"（{user_name} {user_phone}）" if user_name else ""
        extra = f"，备注：{special_request}" if special_request else ""
        return {
            "success": True,
            "booking_id": booking_id,
            "restaurant": restaurant_name,
            "time": time.strftime("%Y-%m-%d %H:%M"),
            "people": people,
            "special_request": special_request,
            "user_name": user_name,
            "user_phone": user_phone,
            "message": f"✅ 已预订【{restaurant_name}】{people} 位，{time.strftime('%H:%M')} 就餐{extra}，预订号：{booking_id} {contact}",
        }
