"""敏感信息脱敏测试"""
from __future__ import annotations

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
