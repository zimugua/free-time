"""
餐厅搜索工具与排队查询工具
从 data 包读取餐厅数据
"""
import random
from datetime import datetime
from typing import List, Dict, Optional

from .base import Tool
from data.restaurants import MOCK_RESTAURANTS


def _all_restaurants() -> List[Dict]:
    """返回所有场景的完整餐厅列表（去重）"""
    seen = set()
    result = []
    for restaurants in MOCK_RESTAURANTS.values():
        for r in restaurants:
            key = r["name"]
            if key not in seen:
                seen.add(key)
                result.append(r)
    return result


class SearchRestaurantsTool(Tool):
    """
    搜索适合场景和人数的餐厅。

    支持两种模式：
    1. 用户指定了餐饮类型 → 仅搜索关键词匹配的结果（最多3个），
       搜不到则返回空列表（由上层提示用户）
    2. 用户未指定 → 按场景 + 低卡偏好推荐
    """

    def __init__(self):
        super().__init__("search_restaurants")

    def run(
        self,
        scene: str,
        people_count: int,
        low_calorie: bool = False,
        specified_keyword: str = "",
    ) -> Dict:
        """
        :param scene: 'family' 或 'friends'
        :param people_count: 用餐人数
        :param low_calorie: 是否优先低卡餐厅
        :param specified_keyword: 用户指定的餐饮关键词（如"火锅"、"烤肉"）
        :return: {
            "restaurants": list,      # 餐厅列表（1-3家）
            "specified_found": bool,  # 是否找到了用户指定的餐厅
            "not_found": bool,        # 用户有指定但搜索不到
        }
        """
        # ---- 模式1：用户指定了餐饮关键词 ----
        if specified_keyword and specified_keyword.strip():
            kw = specified_keyword.strip()
            matched = []

            for r in _all_restaurants():
                name_hit = kw in r["name"]
                cuisine_hit = kw in r.get("cuisine", "")
                kw_hit = any(kw in k for k in r.get("keywords", []))
                desc_hit = kw in r.get("description", "")
                if name_hit or cuisine_hit or kw_hit or desc_hit:
                    # 计算相关度分数
                    score = (
                        (2 if name_hit else 0)
                        + (2 if cuisine_hit else 0)
                        + (1 if kw_hit else 0)
                        + (0.5 if desc_hit else 0)
                    )
                    matched.append({"restaurant": r, "score": score})

            if not matched:
                return {
                    "restaurants": [],
                    "specified_found": False,
                    "not_found": True,
                }

            # 按相关度排序，取最多3家
            matched.sort(key=lambda x: -x["score"])
            restaurants = [m["restaurant"] for m in matched[:3]]

            return {
                "restaurants": restaurants,
                "specified_found": True,
                "not_found": False,
            }

        # ---- 模式2：用户未指定，按场景推荐 ----
        # 合并场景餐厅 + all 通用餐厅
        scene_restaurants = MOCK_RESTAURANTS.get(scene, MOCK_RESTAURANTS["family"])
        all_scene = MOCK_RESTAURANTS.get("all", [])

        # family 场景：合并通用，low_calorie 优先过滤
        if scene == "family":
            pool = scene_restaurants + all_scene
            if low_calorie:
                low_cal = [r for r in pool if r.get("low_calorie_options", False)]
                pool = low_cal if low_cal else pool
        else:
            pool = scene_restaurants

        return {
            "restaurants": pool,
            "specified_found": False,
            "not_found": False,
        }


class CheckReservationTool(Tool):
    """查询餐厅当前座位可用性及预计排队时间"""

    def __init__(self):
        super().__init__("check_reservation")

    def run(self, restaurant_name: str, time: datetime, people: int) -> Dict:
        """
        :param restaurant_name: 餐厅名称
        :param time: 预计到达时间
        :param people: 用餐人数
        :return: 可用性及排队信息
        """
        # Mock：80% 概率有位
        available = random.random() > 0.2
        queue_minutes = 0 if available else random.randint(15, 50)
        return {
            "restaurant": restaurant_name,
            "time": time.strftime("%H:%M"),
            "people": people,
            "available": available,
            "queue_minutes": queue_minutes,
            "tip": "" if available else f"预计排队 {queue_minutes} 分钟，建议提前到场或换一家",
        }
