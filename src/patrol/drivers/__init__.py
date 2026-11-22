"""设备驱动包 - 导入即注册

统一在这里导入所有厂商驱动,任何地方 import patrol.drivers 即完成全部注册,
避免依赖调用方记得逐个导入(曾导致 ssh.py 无法获取驱动的 netmiko 类型)。
"""
import patrol.drivers.h3c  # noqa: F401
import patrol.drivers.huawei  # noqa: F401
import patrol.drivers.ruijie  # noqa: F401
import patrol.drivers.sangfor  # noqa: F401
import patrol.drivers.dptech  # noqa: F401
import patrol.drivers.juniper  # noqa: F401
import patrol.drivers.cisco  # noqa: F401
