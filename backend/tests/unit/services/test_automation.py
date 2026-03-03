"""Unit tests for automation service helpers."""

from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from backend.app.services import automation as automation_service


def _automation(**overrides):
    defaults = {
        "start_code": "",
        "start_code_detect": "",
        "start_code_after": "",
        "end_code": "",
        "end_code_detect": "",
        "end_code_after": "",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_needs_gcode_modification_false_without_automation(monkeypatch):
    async def _fake_get(_printer_id: int):
        return None

    monkeypatch.setattr(automation_service, "get_automation_by_printer_id", _fake_get)

    result = await automation_service.needs_gcode_modification(1)

    assert result is False


@pytest.mark.asyncio
async def test_needs_gcode_modification_true_when_code_present(monkeypatch):
    async def _fake_get(_printer_id: int):
        return _automation(start_code="G28")

    monkeypatch.setattr(automation_service, "get_automation_by_printer_id", _fake_get)

    result = await automation_service.needs_gcode_modification(1)

    assert result is True


def test_detect_and_alter_gcode_inserts_start_and_end_with_anchors():
    source = """;HEADER\nM17\n;START_PRINT\nG1 X10\n;END_PRINT\n"""
    automation = _automation(
        start_code="M1002",
        start_code_after=";HEADER",
        end_code="M400",
        end_code_after=";END_PRINT",
    )

    altered = automation_service.detect_and_alter_gcode_content(source, automation)

    assert "M1002" in altered
    assert "M400" in altered
    assert altered.index(";HEADER") < altered.index("M1002")
    assert altered.index("M400") < altered.index(";END_PRINT")


def test_detect_and_alter_gcode_skips_when_detect_marker_exists():
    source = """M1002\n; already contains start marker\nG1 X5\n; END\nM400\n"""
    automation = _automation(
        start_code="M1002",
        start_code_detect="M1002",
        end_code="M400",
        end_code_detect="M400",
    )

    altered = automation_service.detect_and_alter_gcode_content(source, automation)

    assert altered == source


@pytest.mark.asyncio
async def test_create_temp_gcode_with_automation_for_plain_gcode(tmp_path, monkeypatch):
    source_file = tmp_path / "test.gcode"
    source_file.write_text("G28\nG1 X1\n", encoding="utf-8")

    async def _fake_get(_printer_id: int):
        return _automation(start_code="M1002", end_code="M400")

    monkeypatch.setattr(automation_service, "get_automation_by_printer_id", _fake_get)

    temp_path, overall_hash, md5_map = await automation_service.create_temp_gcode_with_automation(source_file, 1)

    try:
        assert temp_path.exists()
        altered = temp_path.read_text(encoding="utf-8")
        assert altered.startswith("M1002")
        assert "M400" in altered
        assert len(overall_hash) == 64
        assert "test.gcode" in md5_map
        assert len(md5_map["test.gcode"]) == 32
    finally:
        automation_service.cleanup_temp_file(temp_path)


@pytest.mark.asyncio
async def test_create_temp_gcode_with_automation_for_3mf_rewrites_md5(tmp_path, monkeypatch):
    source_3mf = tmp_path / "cube.3mf"
    with zipfile.ZipFile(source_3mf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Metadata/model_settings.config", "{}")
        zf.writestr("plate_1.gcode", "G28\nG1 X20\n")
        zf.writestr("plate_1.gcode.md5", "oldhash")

    async def _fake_get(_printer_id: int):
        return _automation(start_code="M1002", end_code="M400")

    monkeypatch.setattr(automation_service, "get_automation_by_printer_id", _fake_get)

    temp_path, overall_hash, md5_map = await automation_service.create_temp_gcode_with_automation(source_3mf, 3)

    try:
        assert temp_path.exists()
        assert len(overall_hash) == 64
        assert "plate_1.gcode" in md5_map

        with zipfile.ZipFile(temp_path, "r") as zf:
            gcode = zf.read("plate_1.gcode").decode("utf-8")
            md5_content = zf.read("plate_1.gcode.md5").decode("utf-8")

        assert gcode.startswith("M1002")
        assert "M400" in gcode
        assert md5_content == md5_map["plate_1.gcode"]
        assert md5_content != "oldhash"
    finally:
        automation_service.cleanup_temp_file(temp_path)


def test_cleanup_temp_file_removes_existing_file(tmp_path):
    temp_file = Path(tmp_path / "to-clean.gcode")
    temp_file.write_text("G28", encoding="utf-8")

    automation_service.cleanup_temp_file(temp_file)

    assert not temp_file.exists()