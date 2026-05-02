"""
用餐时间计算工具
根据活动结束时间判断用餐安排，处理用餐窗口冲突
"""
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional, Tuple

from .base import Tool
from data.meals import MEAL_SLOTS


def _hour_to_time(h: float) -> time:
    """将小数小时转为 time 对象，如 11.5 → 11:30"""
    hours = int(h)
    minutes = int(round((h - hours) * 60))
    return time(hour=hours, minute=minutes)


def _datetime_to_hour(dt: datetime) -> float:
    """将 datetime 转为小数小时，如 11:30 → 11.5"""
    return dt.hour + dt.minute / 60.0


class MealTimeCalculator(Tool):
    """
    用餐时间计算工具。
    
    核心逻辑：
    - 判断活动结束时间是否在某个用餐窗口内
    - 在窗口内 → 直接安排用餐，无需询问
    - 不在窗口内 → 返回可选的用餐调整方案供用户选择
    - 判断活动时段是否与用餐窗口冲突（活动不应在用餐时间进行）
    """

    def __init__(self):
        super().__init__("meal_time_calculator")

    def find_meal_slot(self, dt: datetime) -> Optional[Dict]:
        """
        判断给定时间是否在某个用餐窗口内。
        :param dt: 待判断的时间
        :return: 匹配到的餐段字典，未匹配则返回 None
        """
        h = _datetime_to_hour(dt)
        for slot in MEAL_SLOTS:
            if slot["start_hour"] <= h <= slot["end_hour"]:
                return slot
        return None

    def find_meal_slot_by_name(self, name: str) -> Optional[Dict]:
        """根据餐段名称查找（breakfast/lunch/dinner）"""
        for slot in MEAL_SLOTS:
            if slot["name"] == name:
                return slot
        return None

    def get_next_meal_slot(self, dt: datetime) -> Optional[Dict]:
        """
        获取给定时间之后的下一个用餐窗口。
        :param dt: 参考时间
        :return: 下一个餐段字典
        """
        h = _datetime_to_hour(dt)
        for slot in MEAL_SLOTS:
            if slot["start_hour"] > h:
                return slot
        # 如果今天没有更晚的餐段了，返回明天的早餐
        return MEAL_SLOTS[0]

    def get_adjustment_options(
        self, activity_end: datetime
    ) -> List[Dict]:
        """
        当活动结束时间不在任何用餐窗口时，
        返回可选的用餐时间调整方案。

        规则：
        - 活动结束在餐段窗口内 → 不应走到这里（calculate_meal_arrangement 已直接安排）
        - 活动结束不在餐段窗口 → 给出选项：
          - 选项1：活动结束后立即用餐（归入最近的餐段）
          - 选项2：下一个餐段的开始时间
        - 去重：两个选项时间相同则只保留一个
        
        :param activity_end: 活动结束时间
        :return: 调整方案列表（最多2个），每个包含：
            - meal_name: 餐段名称
            - meal_label: 餐段中文名
            - suggested_time: 建议用餐时间 (datetime)
            - description: 描述
        """
        h = _datetime_to_hour(activity_end)
        date = activity_end.date()
        options = []

        # 确定最近的下一个餐段
        next_slot = None
        for slot in MEAL_SLOTS:
            if h < slot["start_hour"]:
                next_slot = slot
                break

        # --- 选项1：活动结束后立即用餐（归入最近的餐段） ---
        # 找到活动结束时间最接近的餐段
        nearest_slot = None
        min_gap = float('inf')
        for slot in MEAL_SLOTS:
            # 计算活动结束时间到这个餐段中心的距离
            center = (slot["start_hour"] + slot["end_hour"]) / 2
            gap = abs(h - center)
            if gap < min_gap:
                min_gap = gap
                nearest_slot = slot

        if nearest_slot:
            options.append({
                "meal_name": nearest_slot["name"],
                "meal_label": nearest_slot["label"],
                "suggested_time": activity_end,
                "description": f"活动结束后立即{nearest_slot['label']}（{activity_end.strftime('%H:%M')}）",
            })

        # --- 选项2：下一个餐段的开始时间 ---
        if next_slot:
            suggested_dt = datetime.combine(
                date, _hour_to_time(next_slot["start_hour"])
            )
            gap_minutes = int((next_slot["start_hour"] - h) * 60)
            options.append({
                "meal_name": next_slot["name"],
                "meal_label": next_slot["label"],
                "suggested_time": suggested_dt,
                "description": f"等待后{next_slot['label']}（{suggested_dt.strftime('%H:%M')}，活动结束后约{gap_minutes}分钟）",
            })

        # 去重：如果两个选项的 suggested_time 相同，只保留一个
        if len(options) >= 2:
            seen_times = set()
            unique_options = []
            for opt in options:
                time_key = opt["suggested_time"].strftime("%H:%M")
                if time_key not in seen_times:
                    seen_times.add(time_key)
                    unique_options.append(opt)
            options = unique_options

        return options

    def check_activity_meal_conflict(
        self, start: datetime, duration_hours: float
    ) -> List[Dict]:
        """
        检查活动时段是否与用餐窗口冲突。
        活动不应在用餐时间内进行。
        
        :param start: 活动开始时间
        :param duration_hours: 活动时长
        :return: 冲突的餐段列表
        """
        start_h = _datetime_to_hour(start)
        end_h = start_h + duration_hours

        conflicts = []
        for slot in MEAL_SLOTS:
            # 活动时段与餐段有重叠
            if start_h < slot["end_hour"] and end_h > slot["start_hour"]:
                conflicts.append(slot)
        return conflicts

    def calculate_meal_arrangement(
        self, activity_end: datetime
    ) -> Dict:
        """
        综合计算用餐安排。
        
        :param activity_end: 活动结束时间
        :return: {
            "in_meal_slot": bool,      # 活动结束是否在用餐窗口内
            "meal_slot": dict|null,    # 匹配到的餐段
            "meal_time": datetime,     # 建议用餐时间
            "needs_ask": bool,         # 是否需要询问用户
            "options": list,           # 可选方案（needs_ask=True 时有值）
        }
        """
        slot = self.find_meal_slot(activity_end)

        if slot:
            # 在用餐窗口内，直接安排
            meal_time = datetime.combine(
                activity_end.date(), _hour_to_time(slot["start_hour"])
            )
            # 如果活动结束时间已过餐段开始，用餐时间就是活动结束时间
            if activity_end > meal_time:
                meal_time = activity_end

            return {
                "in_meal_slot": True,
                "meal_slot": slot,
                "meal_time": meal_time,
                "needs_ask": False,
                "options": [],
            }
        else:
            # 不在用餐窗口内，需要询问用户
            options = self.get_adjustment_options(activity_end)

            return {
                "in_meal_slot": False,
                "meal_slot": None,
                "meal_time": None,
                "needs_ask": True,
                "options": options if options else [],
            }
