"""敏感信息脱敏测试"""
from __future__ import annotations

import pytest

from patrol.utils.redact import redact


class TestRedact:
    def test_redact_password(self):
        text = "password MySecret123"
        result = redact(text)
        assert "MySecret123" not in result
        assert "******" in result

    def test_redact_secret(self):
        text = "secret abcdefg"
        result = redact(text)
        assert "abcdefg" not in result

    def test_redact_snmp_community(self):
        text = "snmp-agent community read MyCommunity"
        result = redact(text)
        assert "MyCommunity" not in result

    def test_redact_super_password(self):
        text = "super password simple 123456"
        result = redact(text)
        assert "123456" not in result

    def test_no_redact_normal_text(self):
        text = "interface GigabitEthernet1/0/1\n ip address 192.168.1.1 255.255.255.0"
        result = redact(text)
        assert result == text

    def test_redact_preserves_structure(self):
        text = "password abc123\nip address 10.0.0.1"
        result = redact(text)
        assert "ip address 10.0.0.1" in result


class TestVendorSyntax:
    """各厂商设备配置里真实的口令/团体字/密钥写法,值都不得留在结果里。"""

    @pytest.mark.parametrize("line,secret", [
        # 华为 / H3C 本地用户
        (" local-user admin password simple MyP@ssw0rd", "MyP@ssw0rd"),
        (" local-user admin password cipher %^%#AbCd1234=%^%#", "%^%#AbCd1234"),
        (" local-user admin password irreversible-cipher $1$abc$xyz", "$1$abc$xyz"),
        (" super password simple Sup3rSecret", "Sup3rSecret"),
        # SNMP 团体字(三种写法)
        ("snmp-agent community read C0mmunityKEY", "C0mmunityKEY"),
        ("snmp-server community C0mmunityKEY RO", "C0mmunityKEY"),
        (" snmp community C0mmunityKEY ro", "C0mmunityKEY"),
        # SNMPv3 用户(认证/加密密钥)
        ("snmp-agent usm-user v3 mon group privacy md5 AuthK3y priv des56 PrivK3y",
         "AuthK3y"),
        ("snmp-server user admin grp v3 auth md5 AuthK3y priv des56 PrivK3y",
         "PrivK3y"),
        # 路由协议认证
        (" ospf authentication-mode md5 1 cipher OspfK3y", "OspfK3y"),
        (" ip ospf message-digest-key 1 md5 OspfK3y", "OspfK3y"),
        # IPSec / IKE / NTP / 密钥链
        (" pre-shared-key cipher PskK3y", "PskK3y"),
        (" crypto isakmp key IkeK3y address 10.1.1.1", "IkeK3y"),
        (" ntp-service authentication-keyid 42 md5 NtpK3y", "NtpK3y"),
        (" key-string KeyStr", "KeyStr"),
        (" authorization key 123456", "123456"),
        # 锐捷 / 类 IOS
        (" enable secret 5 $1$abc$hash", "$1$abc$hash"),
        (" username admin privilege 15 secret 5 $1$abc$hash", "$1$abc$hash"),
    ])
    def test_secret_removed(self, line, secret):
        assert secret not in redact(line)

    @pytest.mark.parametrize("line", [
        " password-control length 8",          # H3C 口令策略(纯开关,无值)
        " password-control enable",
        " undo password-recover",
        " ssh server enable",
        " line vty 0 4",
        " ip address 10.1.1.1 255.255.255.0",
        " stp instance 0 priority 4096",
        " interface GigabitEthernet0/0/1",
    ])
    def test_non_secret_lines_untouched(self, line):
        assert redact(line) == line

    def test_only_the_matching_line_is_masked(self):
        """关键字落在行尾时,不得把下一行的首个词一起遮掉。"""
        text = " authentication-mode password\n ip address 10.1.1.1 255.255.255.0\n"
        assert "ip address 10.1.1.1 255.255.255.0" in redact(text)

    def test_idempotent(self):
        text = " local-user admin password simple MyP@ssw0rd\n vlan 10\n"
        assert redact(redact(text)) == redact(text)

    def test_bare_keyword_line_kept(self):
        assert redact(" password\n") == " password\n"

    def test_empty_and_none_like_input(self):
        assert redact("") == ""
