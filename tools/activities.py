"""
活动搜索工具
从 data 包读取活动数据，支持优先匹配用户指定活动 + 自动补充生成差异化方案
"""
from datetime import datetime
from typing import List, Dict

from .base import Tool
from data.activities import MOCK_ACTIVITIES


class SearchActivitiesTool(Tool):
    """
    搜索适合当前场景的活动，生成差异化方案。

    支持两种模式：
    1. 用户指定了具体活动 → 仅搜索与关键词匹配的结果（最多3个），
       搜不到则返回空列表（由上层提示用户）
    2. 用户未指定 → 自动搜索生成3个差异化方案
    """

    def __init__(self):
        super().__init__("search_activities")

    def run(
        self,
        scene: str,
        start_time: datetime,
        duration_hours: float,
        specified_activity: str = "",
    ) -> Dict:
        """
        :param scene: 'family' 或 'friends'
        :param start_time: 活动开始时间
        :param duration_hours: 可用总时长（小时）
        :param specified_activity: 用户指定的活动名称关键词（如"密室"、"博物馆"）
        :return: {
            "specified_found": bool,    # 是否找到了用户指定的活动
            "not_found": bool,          # 用户有指定但搜索不到
            "specified_activity": dict, # 第一个匹配到的活动（指定模式用）
            "plans": list               # 方案列表（1-3个）
        }
        """
        # ---- 模式1：用户指定了活动关键词 ----
        if specified_activity and specified_activity.strip():
            kw = specified_activity.strip()

            # 从所有活动中搜索关键词匹配（不限场景，取时长合适的）
            matched = []
            for a in MOCK_ACTIVITIES:
                if a["duration_hours"] > duration_hours:
                    continue  # 时长超出，跳过
                name_hit = kw in a["name"]
                tag_hit = any(kw in tag for tag in a.get("tags", []))
                desc_hit = kw in a.get("description", "")
                if name_hit or tag_hit or desc_hit:
                    matched.append({
                        "activity": a,
                        # 匹配优先级：名称命中 > tag命中 > 描述命中
                        "score": (2 if name_hit else 0) + (1 if tag_hit else 0) + (0.5 if desc_hit else 0),
                    })

            if not matched:
                # 搜索不到指定活动
                return {
                    "specified_found": False,
                    "not_found": True,
                    "specified_activity": None,
                    "plans": [],
                }

            # 按分数排序，取最多3个最相关的
            matched.sort(key=lambda x: -x["score"])
            plans = [m["activity"] for m in matched[:3]]

            return {
                "specified_found": True,
                "not_found": False,
                "specified_activity": plans[0],
                "plans": plans,
            }

        # ---- 模式2：用户未指定，自动推荐差异化方案 ----
        candidates = [
            a for a in MOCK_ACTIVITIES
            if a["scene"] == scene and a["duration_hours"] <= duration_hours
        ]

        # 候选不足时放宽场景限制
        if len(candidates) < 3:
            extra = [
                a for a in MOCK_ACTIVITIES
                if a not in candidates and a["duration_hours"] <= duration_hours
            ]
            candidates.extend(extra)

        def _diversity_score(pool: List[Dict], selected_tags: set) -> List[Dict]:
            """对候选活动按差异化程度打分排序"""
            scored = []
            for a in pool:
                a_tags = set(a.get("tags", []))
                overlap = len(a_tags & selected_tags)
                scored.append((-overlap, a))
            scored.sort(key=lambda x: x[0])
            return [a for _, a in scored]

        plans = []
        used_tags = set()

        diversity_sorted = _diversity_score(candidates, used_tags)
        for act in diversity_sorted:
            if len(plans) >= 3:
                break
            plans.append(act)
            used_tags.update(act.get("tags", []))

        return {
            "specified_found": False,
            "not_found": False,
            "specified_activity": None,
            "plans": plans[:3],
        }
