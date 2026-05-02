"""
用餐时间配置
修改此文件可调整餐段定义。

字段说明：
- name: 餐段名称
- start_hour: 开始时间（小时，如 11.5 = 11:30）
- end_hour: 结束时间（小时，如 18.5 = 18:30）
- duration_minutes: 用餐时长（分钟）
"""

MEAL_SLOTS = [
    {
        "name": "breakfast",
        "label": "早餐",
        "start_hour": 7.0,
        "end_hour": 8.0,
        "duration_minutes": 60,
    },
    {
        "name": "lunch",
        "label": "午餐",
        "start_hour": 11.5,
        "end_hour": 12.5,
        "duration_minutes": 60,
    },
    {
        "name": "dinner",
        "label": "晚餐",
        "start_hour": 17.5,
        "end_hour": 18.5,
        "duration_minutes": 60,
    },
]
