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
 10.25.158.35    1     Full/DR         00:00:32    Vlanif10""",
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
        "vendor": "zte", "device_type": "zxr10_switch",
        "name": "样例-中兴5250", "model": "5250-28PS-E",
        "software_version": "V3.1.0", "host_hint": "接入交换机",
        "responses": {
            "show version": """ZTE ZXR10 5250 Series Software, Version V3.1.0
Copyright (c) 2001-2026 ZTE Corporation.
ZXR10 5250-28PS-E uptime is 12 weeks, 3 days, 4 hours, 56 minutes""",
            "show cpu": """CPU utilization in 5 seconds: 8.3%
CPU utilization in 1 minute : 7.9%
CPU utilization in 5 minutes: 7.5%""",
            "show memory": """System Total Memory(bytes): 1073741824
Total Used Memory(bytes): 279134208
Memory Used Rate: 26%""",
            "show ip interface brief": """Interface         IP-Address      Mask          Admin  Phy   Prot
gei-1/1/1         10.1.1.1        255.255.255.0 up     up    up
vlan10            192.168.10.1    255.255.255.0 up     up    up
gei-1/1/24        unassigned      --            up     down  down""",
            "show logging": """Jul 12 2026 10:23:45 sw-acc %%01SYS/2/REBOOT(l): System rebooted by user
Jul 12 2026 08:00:11 sw-acc %%01SEC/5/LOGIN(l): SSH login succeeded""",
            "show lldp neighbors": """gei-1/1/1          core-sw            gei-1/1/24
gei-1/1/2          ap-floor3          eth0""",
            "show running-config": """hostname sw-acc
ssh-server enable
snmp-server community zte-public RO
spanning-tree enable
line vty 0 4
 login local
 protocol input ssh""",
        },
    },
    {
        "vendor": "maipu", "device_type": "mypower_switch",
        "name": "样例-迈普S3100", "model": "S3100V2-24GT4XS",
        "software_version": "2.10.13", "host_hint": "接入交换机",
        "responses": {
            "show version": """MyPower Operating System Software
MyPower S3100V2 Software Version 2.10.13
MyPower S3100V2-24GT4XS uptime is 15 weeks, 1 day, 2 hours""",
            "show processes cpu": """CPU utilization in five seconds: 12%/2%; one minute: 9%; five minutes: 7%""",
            "show memory statistics": """                Head      Total(b)     Used(b)     Free(b)
Processor  0x1A2B3C  262144000    89128960    173015040""",
            "show ip interface brief": """Interface              IP-Address      OK? Method Status                Protocol
Vlan1                  192.168.10.1    YES NVRAM  up                    up
GigabitEthernet0/2     unassigned      YES unset   down                 down""",
            "show logging": """Jul 08 10:23:45.123: %LINK-3-UPDOWN: Interface GigabitEthernet0/2, changed state to down
Jul 08 09:00:01.220: %SYS-6-BOOTTIME: System restarted""",
            "show lldp neighbors": """Gi0/1              core-sw            Gi1/0/24
Gi0/2              ap-floor3          eth0""",
            "show running-config": """hostname mp-acc
ssh-server enable
snmp-server community public RO
spanning-tree mode rstp
line vty 0 4
 login local
 transport input ssh""",
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
