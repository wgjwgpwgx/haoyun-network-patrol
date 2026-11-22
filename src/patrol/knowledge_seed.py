"""内置种子设备数据集(精简版真实风格回显)

一份数据两用:
  1. 知识库种子语料(开箱即有的样例,可浏览/Copilot 取样)
  2. 模拟设备服务器的命令响应表(无真机端到端演示/培训/自测)
"""
from __future__ import annotations

SEED_DEVICES: list[dict] = [
    {
        "vendor": "huawei", "device_type": "vrp_switch",
        "name": "样例-华为S5735", "model": "S5735-S48P4X",
        "software_version": "V500R019C10SPC500", "host_hint": "接入交换机",
        "responses": {
            "display version": """VRP (R) software, Version 5.170 (S5735-S48P4X V500R019C10SPC500)
Copyright (C) 2000-2024 Huawei Technologies Co., Ltd.
HUAWEI S5735-S48P4X uptime is 35 weeks, 4 days, 22 hours, 13 minutes""",
            "display cpu-usage": """CPU Usage: 14%   Max: 72%
CPU utilization for ten seconds:14%  one minute:12%  five minutes:11%""",
            "display memory-usage": """System Total Memory Is: 1610612736 bytes
Total Memory Used Is: 418759315 bytes
Memory Using Percentage Is: 26%""",
            "display interface brief": """PHY: Physical
*down: administratively down
(l): loopback
Interface                PHY   Protocol  InUti OutUti   inErrors  outErrors
GigabitEthernet0/0/1     up    up        12%   8%        0         0
GigabitEthernet0/0/2     up    down      0%    0%        0         0
GigabitEthernet0/0/3     down  down      0%    0%        0         0""",
            "display fan": """Fan 1 State: Normal
Fan 2 State: Normal""",
            "display power": """Slot 1: Power 1 State: Normal
Slot 2: Power 2 State: Normal""",
            "display temperature": """Slot No. 1
Temperature status: Normal
Temperature value: 38""",
            "display lldp neighbor brief": """Local Intf   Neighbor Dev             Neighbor Intf
GE0/0/1      core-sw                   GE1/0/24""",
            "display ospf peer": """ Neighbor ID     Pri   State           Dead Time   Interface
 192.168.158.35    1     Full/DR         00:00:32    Vlanif10""",
            "display current-configuration": """#
 sysname access-sw
 telnet server enable
 snmp-agent community read %"Public@2026"%
user-interface vty 0 4
 authentication-mode password
 set authentication password cipher %^%#x%^%#
 idle-timeout 5
 protocol inbound all
#
return""",
        },
    },
    {
        "vendor": "h3c", "device_type": "s7506e",
        "name": "样例-H3C-S7506E", "model": "S7506E-V",
        "software_version": "R7507P12", "host_hint": "核心交换机",
        "responses": {
            "display version": """H3C Comware Platform Software
Software Version is 7.1.070, ESS 2311
H3C S7506E-V uptime is 0 years, 30 weeks, 2 days""",
            "display cpu": """Slot 1 CPU 0 CPU usage: 8% in last 5 seconds""",
            "display memory": """The statistics of memory:
Slot 1: Total 2048 MB, Used 612 MB, Free 1436 MB""",
            "display environment": """System temperature information:
Slot 1
  Sensor 1: 39 C""",
            "display lldp neighbor-information list": """LLDP neighbor-information of port 1[GigabitEthernet1/0/1]:
  PortID/Subtype   :GigabitEthernet2/0/24
  System name      :access-sw""",
            "display current-configuration": """#
 sysname core-sw
 undo telnet server enable
 snmp-agent community read read@2026
user-interface vty 0 4
 authentication-mode scheme
 idle-timeout 5
#
return""",
        },
    },
    {
        "vendor": "cisco", "device_type": "ios_switch",
        "name": "样例-Cisco2960S", "model": "WS-C2960S-48TS-L",
        "software_version": "15.2(2)E9", "host_hint": "接入交换机",
        "responses": {
            "show version": """Cisco IOS Software, C2960S Software (C2960S-UNIVERSALK9-M), Version 15.2(2)E9
cisco WS-C2960S-48TS-L (PowerPC405) processor
WS-C2960S-48TS-L uptime is 30 weeks, 2 days, 3 hours, 55 minutes""",
            "show processes cpu": """CPU utilization for five seconds: 8%/0%; one minute: 5%; five minutes: 4%""",
            "show memory statistics": """            Head    Total(b)     Used(b)     Free(b)
Processor  0x02AA5B90   62197760     25127720    37070040""",
            "show ip interface brief": """Interface              IP-Address      OK? Method Status                Protocol
Vlan1                  192.168.10.1    YES NVRAM  up                    up
GigabitEthernet0/1     unassigned      YES NVRAM  up                    up
GigabitEthernet0/2     unassigned      YES unset   down                 down""",
            "show env all": """Fan Status:
  Fan 1
    Status:  OK
POWER SUPPLIES:
  Power Supply 1
    Status:  OK""",
            "show lldp neighbors": """Device ID           Local Intf     Hold-time  Capability  Port ID
core-sw             Gi0/1          120        B,R         Gi1/0/24""",
            "show running-config": """hostname sw-access
aaa new-model
spanning-tree mode rapid-pvst
line vty 0 4
 transport input ssh
snmp-server community public RO""",
        },
    },
    {
        "vendor": "juniper", "device_type": "junos",
        "name": "样例-JuniperEX4300", "model": "ex4300-48t",
        "software_version": "21.4R3-S5.2", "host_hint": "接入交换机",
        "responses": {
            "show version": """Hostname: ex-access
Model: ex4300-48t
Junos: 21.4R3-S5.2""",
            "show chassis routing-engine": """Routing Engine status:
    CPU utilization:
      User        1 percent
      Idle       97 percent
    Memory utilization           22 percent""",
            "show interfaces terse": """Interface               Admin Link Proto
ge-0/0/0                up    up
ge-0/0/1                up    down
ge-0/0/2                down  down""",
            "show chassis environment": """Class Item                   Status
Power Power Supply 0         OK
Fan  Fan Tray 0             OK""",
            "show system alarms": """No alarms currently active""",
            "show configuration system services": """ssh {
    root-login deny;
}
web-management {
    https {
        system-generated-certificate;
    }
}""",
        },
    },
    {
        "vendor": "ruijie", "device_type": "rgos_switch",
        "name": "样例-锐捷S5750", "model": "S5750C-24GT4S",
        "software_version": "RGOS 10.4(3b14)", "host_hint": "接入交换机",
        "responses": {
            "show version": """Ruijie Full Services Software Platform Software
RGOS 10.4(3b14) Release(191117)
S5750C-24GT4S uptime is 20 weeks""",
            "show cpu": """CPU usage: 12% in last 5 seconds""",
            "show memory": """Memory: Total 512M, Used 198M, Free 314M""",
            "show ip interface brief": """Interface                IP-Address      OK? Status    Protocol
Vlan 1                   192.168.20.1    YES up        up
GigabitEthernet 0/1      unassigned      YES up        up
GigabitEthernet 0/2      unassigned      NO  down      down""",
            "show lldp neighbors": """Device ID       Local Interface   Port ID
core-sw         Gi0/25            Gi1/0/1""",
        },
    },
]
