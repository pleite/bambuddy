# Automation Feature - Testing & Validation Strategy

**Date:** February 25, 2026

---

## 📋 Testing Overview

The automation feature modifications span two main service files with integration points in the dispatch system. Testing strategy focuses on:

1. **Unit Tests** - Service layer logic
2. **Integration Tests** - End-to-end reprint/print flows
3. **Edge Case Tests** - Error conditions and graceful degradation
4. **Manual Testing** - UI/UX verification

---

## 🧪 Unit Tests

### File: `tests/unit/services/test_automation.py`

#### Test 1: Detect Modification Need
```python
@pytest.mark.asyncio
async def test_needs_gcode_modification_true():
    """Should return True when automation exists with codes."""
    # Setup
    automation = Automation(
        printer_id=1,
        start_code="G28",
        start_code_detect="",
        end_code="M104 S0",
    )
    db_mock = MagicMock()
    # ... mock async session
    
    # Execute
    result = await needs_gcode_modification(1)
    
    # Assert
    assert result is True
    
@pytest.mark.asyncio
async def test_needs_gcode_modification_false_no_config():
    """Should return False when no automation configured."""
    # Mock: db returns None
    result = await needs_gcode_modification(999)
    assert result is False

@pytest.mark.asyncio
async def test_needs_gcode_modification_false_no_codes():
    """Should return False when automation exists but no codes set."""
    # automation with empty codes
    result = await needs_gcode_modification(1)
    assert result is False
```

#### Test 2: GCode Modification Logic
```python
def test_detect_and_alter_gcode_basic():
    """Should inject start and end codes."""
    original = "; header\nG28\nG29\n; footer"
    automation = Automation(
        start_code="G0 X0 Y0",
        start_code_detect="",
        start_code_after="G28",
        end_code="M104 S0",
        end_code_detect="",
        end_code_after="G29",
    )
    
    result = detect_and_alter_gcode_content(original, automation)
    
    assert "G0 X0 Y0" in result
    assert "M104 S0" in result
    # Verify order
    lines = result.split("\n")
    assert lines.index("G0 X0 Y0") > lines.index("G28")
    assert lines.index("M104 S0") > lines.index("G29")

def test_detect_and_alter_skip_if_marker_exists():
    """Should skip injection if detection marker found."""
    original = "; header\n; ALREADY_PROCESSED\nG28"
    automation = Automation(
        start_code="G0 X0 Y0",
        start_code_detect="ALREADY_PROCESSED",
        start_code_after="",
        end_code="",
        end_code_detect="",
        end_code_after="",
    )
    
    result = detect_and_alter_gcode_content(original, automation)
    
    # Should NOT inject start code
    assert result.count("G0 X0 Y0") == 0

def test_detect_and_alter_insert_at_beginning_if_no_anchor():
    """If no start_code_after anchor, insert at beginning."""
    original = "G28\nG29"
    automation = Automation(
        start_code="G0 X0",
        start_code_detect="",
        start_code_after="",  # No anchor
        end_code="",
        end_code_detect="",
        end_code_after="",
    )
    
    result = detect_and_alter_gcode_content(original, automation)
    lines = result.split("\n")
    
    assert lines[0] == "G0 X0"
    assert lines[1] == "G28"
```

#### Test 3: Temp File Creation
```python
@pytest.mark.asyncio
async def test_create_temp_gcode_basic():
    """Should create temp .gcode file with modifications."""
    # Create temp original file
    with tempfile.NamedTemporaryFile(suffix=".gcode", delete=False) as f:
        f.write("G28\nG29".encode())
        original_path = Path(f.name)
    
    try:
        # Setup
        automation = Automation(
            id=1,
            printer_id=1,
            start_code="G0 X0",
            start_code_detect="",
            start_code_after="",
            end_code="M104 S0",
            end_code_detect="",
            end_code_after="",
        )
        # Mock db...
        
        # Execute
        temp_path, file_hash, md5_dict = await create_temp_gcode_with_automation(
            original_path, 1
        )
        
        # Assert
        assert temp_path.exists()
        assert temp_path != original_path
        assert file_hash  # SHA256 hash
        assert md5_dict[original_path.name]  # MD5 for file
        
        # Verify modification
        with open(temp_path) as f:
            content = f.read()
            assert "G0 X0" in content
            assert "M104 S0" in content
    finally:
        original_path.unlink()
        temp_path.unlink()

@pytest.mark.asyncio
async def test_create_temp_3mf_with_modifications():
    """Should modify all .gcode files inside 3MF."""
    # Create temp 3MF (which is a ZIP)
    with tempfile.NamedTemporaryFile(suffix=".3mf", delete=False) as f:
        original_path = Path(f.name)
    
    try:
        # Create sample 3MF with gcode files
        with zipfile.ZipFile(original_path, "w") as zf:
            zf.writestr("Metadata/plate_1.gcode", "G28\nG29")
            zf.writestr("model.xml", "<model/>")
        
        # Execute
        temp_path, file_hash, md5_dict = await create_temp_gcode_with_automation(
            original_path, 1  # (with automation mocked)
        )
        
        # Assert
        assert temp_path.exists()
        assert temp_path != original_path
        assert "Metadata/plate_1.gcode" in md5_dict
        assert "Metadata/plate_1.gcode.md5" in md5_dict
        
        # Verify 3MF contents
        with zipfile.ZipFile(temp_path, "r") as zf:
            gcode_content = zf.read("Metadata/plate_1.gcode").decode()
            assert "G0 X0" in gcode_content
            assert "M104 S0" in gcode_content
            
            # MD5 file should exist
            md5_content = zf.read("Metadata/plate_1.gcode.md5").decode()
            assert len(md5_content) == 32  # MD5 hex length
    finally:
        original_path.unlink()
        temp_path.unlink()

@pytest.mark.asyncio
async def test_create_temp_unsupported_type():
    """Should raise for unsupported file types."""
    path = Path("/tmp/test.txt")
    
    with pytest.raises(ValueError):
        await create_temp_gcode_with_automation(path, 1)

@pytest.mark.asyncio
async def test_create_temp_no_automation():
    """Should raise if no automation configured."""
    path = Path("/tmp/test.gcode")
    
    # Mock: db returns None
    with pytest.raises(ValueError) as exc:
        await create_temp_gcode_with_automation(path, 999)
    
    assert "No automation data" in str(exc.value)
```

#### Test 4: Cleanup
```python
def test_cleanup_temp_file_success():
    """Should delete temp file successfully."""
    with tempfile.NamedTemporaryFile(delete=False) as f:
        temp_path = Path(f.name)
        f.write(b"test")
    
    assert temp_path.exists()
    
    cleanup_temp_file(temp_path)
    
    assert not temp_path.exists()

def test_cleanup_temp_file_already_deleted():
    """Should handle file already deleted gracefully."""
    temp_path = Path("/tmp/nonexistent_12345.tmp")
    
    # Should not raise
    cleanup_temp_file(temp_path)

def test_cleanup_temp_file_permission_error():
    """Should log warning and continue if permission denied."""
    with tempfile.NamedTemporaryFile(delete=False) as f:
        temp_path = Path(f.name)
    
    # Simulate permission error by making parent read-only
    temp_path.parent.chmod(0o500)
    
    try:
        # Should not raise
        cleanup_temp_file(temp_path)
    finally:
        temp_path.parent.chmod(0o755)
        temp_path.unlink(missing_ok=True)
```

---

## 🔗 Integration Tests

### File: `tests/integration/test_automation_dispatch.py`

#### Test 1: Reprint Archive with Automation
```python
@pytest.mark.asyncio
async def test_reprint_archive_with_automation_enabled(
    db: AsyncSession,
    test_printer: Printer,
    test_archive: PrintArchive,
):
    """Full flow: reprint archive with automation applied."""
    # Setup
    # 1. Enable automation on printer
    test_printer.plate_automation_enabled = True
    
    # 2. Create automation config
    automation = Automation(
        printer_id=test_printer.id,
        start_code="G0 X0 Y0",
        start_code_detect="",
        start_code_after="",
        end_code="M104 S0",
        end_code_detect="",
        end_code_after="",
    )
    db.add(automation)
    await db.commit()
    
    # 3. Mock FTP operations
    with mock.patch("backend.app.services.bambu_ftp.upload_file_async") as mock_upload:
        with mock.patch("backend.app.services.bambu_ftp.delete_file_async"):
            with mock.patch("backend.app.services.printer_manager.printer_manager.start_print"):
                mock_upload.return_value = True
                
                # Execute: Dispatch reprint
                result = await background_dispatch.dispatch_reprint_archive(
                    archive_id=test_archive.id,
                    archive_name=test_archive.filename,
                    printer_id=test_printer.id,
                    printer_name=test_printer.name,
                    options=ReprintRequest(plate_id=1).model_dump(exclude_none=True),
                    requested_by_user_id=None,
                    requested_by_username=None,
                )
    
    # Assert
    assert result["dispatch_job_id"] is not None
    
    # Wait for background job to complete
    await asyncio.sleep(0.5)
    
    # Verify upload was called with modified file
    mock_upload.assert_called_once()
    call_args = mock_upload.call_args
    
    # The file path passed to upload should be a temp file (different from original)
    # OR we track was_modified flag in mock
    
    # TODO: Verify gcode was modified by checking dispatch state/logs


@pytest.mark.asyncio
async def test_reprint_archive_automation_disabled(
    db: AsyncSession,
    test_printer: Printer,
    test_archive: PrintArchive,
    caplog,
):
    """Should use original file if automation disabled."""
    # Setup
    test_printer.plate_automation_enabled = False
    await db.commit()
    
    with mock.patch("backend.app.services.bambu_ftp.upload_file_async") as mock_upload:
        with mock.patch("backend.app.services.bambu_ftp.delete_file_async"):
            with mock.patch("backend.app.services.printer_manager..."):
                mock_upload.return_value = True
                
                # Execute
                result = await background_dispatch.dispatch_reprint_archive(...)
    
    # Assert
    assert "applying automation" not in caplog.text.lower()
    
    # Original file should be uploaded (size check)
    original_size = (settings.base_dir / test_archive.file_path).stat().st_size
    call_args = mock_upload.call_args
    uploaded_size = Path(call_args[0][2]).stat().st_size
    
    assert uploaded_size == original_size


@pytest.mark.asyncio
async def test_reprint_archive_automation_fails_gracefully(
    db: AsyncSession,
    test_printer: Printer,
    test_archive: PrintArchive,
    caplog,
):
    """Should fallback to original file if automation fails."""
    # Setup
    test_printer.plate_automation_enabled = True
    
    # Automation config missing (not created)
    await db.commit()
    
    with mock.patch("backend.app.services.bambu_ftp.upload_file_async") as mock_upload:
        with mock.patch("backend.app.services.bambu_ftp.delete_file_async"):
            with mock.patch("backend.app.services.printer_manager..."):
                mock_upload.return_value = True
                
                # Execute
                result = await background_dispatch.dispatch_reprint_archive(...)
    
    # Assert
    assert "Failed to apply automation" in caplog.text
    assert result is not None  # Job still succeeded
    
    # Original file was uploaded
    original_size = (settings.base_dir / test_archive.file_path).stat().st_size
    call_args = mock_upload.call_args
    uploaded_size = Path(call_args[0][2]).stat().st_size
    
    assert uploaded_size == original_size
```

#### Test 2: Library File Print with Automation
```python
@pytest.mark.asyncio
async def test_print_library_file_with_automation(
    db: AsyncSession,
    test_printer: Printer,
    test_library_file: LibraryFile,
):
    """Full flow: print library file with automation applied."""
    # Setup
    test_printer.plate_automation_enabled = True
    automation = Automation(
        printer_id=test_printer.id,
        start_code="G0 X0 Y0",
        start_code_detect="",
        start_code_after="",
        end_code="M104 S0",
        end_code_detect="",
        end_code_after="",
    )
    db.add(automation)
    await db.commit()
    
    with mock.patch("...upload_file_async") as mock_upload:
        with mock.patch("...delete_file_async"):
            with mock.patch("...printer_manager.start_print"):
                mock_upload.return_value = True
                
                # Execute
                result = await background_dispatch.dispatch_print_library_file(
                    file_id=test_library_file.id,
                    filename=test_library_file.filename,
                    printer_id=test_printer.id,
                    printer_name=test_printer.name,
                    options=FilePrintRequest().model_dump(exclude_none=True),
                    requested_by_user_id=None,
                    requested_by_username=None,
                )
    
    # Assert
    assert result is not None
    
    # Job should complete with modified file
    await asyncio.sleep(0.5)
    
    # Verify archive was created
    service = ArchiveService(db)
    archives = await service.list_archives(printer_id=test_printer.id)
    assert len(archives) > 0
```

---

## 🎯 Edge Case Tests

### File: `tests/unit/services/test_automation_edge_cases.py`

#### Test 1: Special Characters in GCode
```python
def test_detect_and_alter_gcode_with_special_chars():
    """Should handle special characters in gcode."""
    original = "; Comment with unicode: 日本語\nG28"
    automation = Automation(
        start_code="G0 X0",
        ...,
    )
    
    result = detect_and_alter_gcode_content(original, automation)
    
    assert "日本語" in result  # Preserved
    assert "G0 X0" in result   # Injected
```

#### Test 2: Large Files
```python
@pytest.mark.asyncio
async def test_create_temp_large_3mf():
    """Should handle 100MB+ 3MF files efficiently."""
    # Create large 3MF with 50MB gcode
    # Verify no memory explosion
    # Verify temp file created in reasonable time (<5s)
```

#### Test 3: Already Modified Files
```python
def test_double_injection_prevented():
    """Should not inject twice if detection marker present."""
    # File already has start code
    original = "; AUTOMATION_START\nG0 X0 Y0\nG28"
    
    automation = Automation(
        start_code="G0 X0 Y0",
        start_code_detect="AUTOMATION_START",
        ...,
    )
    
    result = detect_and_alter_gcode_content(original, automation)
    
    # Should only have one G0 X0 Y0
    assert result.count("G0 X0 Y0") == 1
```

#### Test 4: Corrupted Files
```python
@pytest.mark.asyncio
async def test_create_temp_corrupted_gcode():
    """Should handle invalid UTF-8 gracefully."""
    path = Path("/tmp/test.gcode")
    with open(path, "wb") as f:
        f.write(b"\xFF\xFE" + b"G28")  # Invalid UTF-8
    
    try:
        # Should handle with errors='ignore'
        temp_path, _, _ = await create_temp_gcode_with_automation(path, 1)
        assert temp_path.exists()
    finally:
        path.unlink()
        temp_path.unlink()
```

---

## ✅ Manual Testing Checklist

### Scenario 1: Reprint Archive with Automation
- [ ] Create printer
- [ ] Enable `plate_automation_enabled`
- [ ] Create automation config with start/end codes
- [ ] Complete a print to create archive
- [ ] Reprint archive
  - [ ] Verify WebSocket shows "Checking automation..."
  - [ ] Verify WebSocket shows "Automation applied"
  - [ ] Verify print completes successfully
  - [ ] Verify temp file was cleaned up (check /tmp)
- [ ] Monitor logs for correct flow
- [ ] Verify gcode on printer was modified (via printer API)

### Scenario 2: Library File Print with Automation
- [ ] Upload .gcode or .3mf file to library
- [ ] Print file with automation enabled
  - [ ] Verify archive created
  - [ ] Verify WebSocket shows automation status
  - [ ] Print completes
- [ ] Verify temp file cleaned up

### Scenario 3: Automation Disabled
- [ ] Disable `plate_automation_enabled`
- [ ] Try reprint/library print
- [ ] Verify no "automation applied" messages
- [ ] Verify original file uploaded
- [ ] Print completes normally

### Scenario 4: No Automation Config
- [ ] Enable `plate_automation_enabled`
- [ ] Don't create Automation record
- [ ] Try reprint
- [ ] Verify logs show "No automation data"
- [ ] Verify original file uploaded
- [ ] Print completes (graceful fallback)

### Scenario 5: Automation Config Changes
- [ ] Create automation config
- [ ] Queue multiple reprints
- [ ] Change automation config mid-queue
- [ ] Verify each print uses config as-it-was when dispatch started
- [ ] No race conditions

### Scenario 6: Cancel During Automation
- [ ] Start reprint
- [ ] Cancel during automation check/modification
- [ ] Verify temp file cleaned up
- [ ] Verify error message sensible

### Scenario 7: Printer Offline
- [ ] Enable automation
- [ ] Take printer offline (simulated)
- [ ] Try reprint
- [ ] Verify error before attempting to apply automation
- [ ] No temp files left behind

---

## 📊 Test Coverage Goals

### Target: >95% for automation.py
- [ ] `get_automation_by_printer_id()` - 100%
- [ ] `needs_gcode_modification()` - 100%
- [ ] `detect_and_alter_gcode_content()` - 98%
- [ ] `create_temp_gcode_with_automation()` - 95%
- [ ] `cleanup_temp_file()` - 100%

### Target: >85% for background_dispatch.py changes
- [ ] `_maybe_apply_automation()` - 90%
- [ ] `_run_reprint_archive()` - 85%
- [ ] `_run_print_library_file()` - 85%

---

## 🔍 Code Review Checklist

### Before Merge
- [ ] All existing tests still pass (`pytest`)
- [ ] New tests added for all code paths
- [ ] Test coverage >90%
- [ ] No new linting errors (`pylint`, `flake8`)
- [ ] Type hints correct (`mypy`)
- [ ] No circular imports
- [ ] Async patterns are correct (no `asyncio.run()`)
- [ ] Error handling is comprehensive
- [ ] Logging is appropriate level (debug/info/warning)
- [ ] Docstrings complete and accurate
- [ ] No hardcoded paths or magic numbers
- [ ] Performance acceptable (<200ms overhead)

### Integration Review
- [ ] Automation API endpoints still work
- [ ] WebSocket events sent correctly
- [ ] Database queries correct
- [ ] File operations safe (race conditions?)
- [ ] Temp file cleanup verified in slow networks
- [ ] Graceful degradation on all error paths

---

## 🐛 Known Test Scenarios to Cover

1. **Temp file cleanup on exception** - Ensure finally blocks always execute
2. **Async/await correctness** - No event loop issues
3. **Large file handling** - Memory efficiency
4. **Multiple concurrent dispatches** - Thread safety
5. **Printer state changes during dispatch** - Robustness
6. **File system edge cases** - Permission errors, disk full
7. **Interruption signals** - Cleanup on SIGTERM, SIGKILL
8. **Mixed automation/non-automation printers** - Isolation

