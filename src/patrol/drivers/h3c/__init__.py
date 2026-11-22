# 导入所有 H3C Driver 以触发 @register 装饰器
from patrol.drivers.h3c import comware_switch  # noqa: F401
from patrol.drivers.h3c import s7506e  # noqa: F401
from patrol.drivers.h3c import secpath_firewall  # noqa: F401
