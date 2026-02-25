# Automation Feature Completion Plan

**Date:** February 25, 2026  
**Feature:** Printer Automation (GCode Modification with Temporary File Generation)

---

## 📋 Current State Analysis

### Existing Infrastructure

#### 1. **Models** ([backend/app/models/automation.py](backend/app/models/automation.py))
- `Automation` model with printer_id relationship
- Fields for start/end automation codes:
  - `start_code`: GCode snippet to inject at start
  - `start_code_detect`: Detection string to skip if already present
  - `start_code_after`: Anchor line to insert after
  - `end_code`: GCode snippet to inject at end
  - `end_code_detect`: Detection string to skip if already present
  - `end_code_after`: Anchor line to insert before

#### 2. **Printer Model Enhancement** ([backend/app/models/printer.py:34](backend/app/models/printer.py#L34))
- `plate_automation_enabled: bool` flag per printer (currently unused in dispatch)
- Relationship: `automation: Mapped[list["Automation"]]`

#### 3. **Schemas** ([backend/app/schemas/automation.py](backend/app/schemas/automation.py))
- `AutomationBase`, `AutomationCreate`, `AutomationUpdate`, `AutomationResponse`
- Full CRUD support through API

#### 4. **API Routes** ([backend/app/api/routes/automation.py](backend/app/api/routes/automation.py))
- ✅ GET `/printers/{printer_id}/automation` - List automation configs
- ✅ POST `/printers/{printer_id}/automation` - Create new automation
- ✅ PATCH `/automation/{automation_id}` - Update existing automation
- ✅ DELETE `/automation/{automation_id}` - Delete automation

#### 5. **Service - Partially Complete** ([backend/app/services/automation.py](backend/app/services/automation.py))
- ✅ `get_automation_by_printer_id()` - Async retrieval
- ✅ `detect_and_alter_gcode_content()` - GCode modification logic with:
  - Detection checks to skip if already applied
  - Anchor-point insertion
  - Start/end code injection
- ✅ `create_temp_gcode_with_automation()` - Temp file creation:
  - Handles `.3mf` files (ZIP-based manipulation)
  - Handles `.gcode` files (plain text modification)
  - Computes hash and MD5 checksums
  - **ISSUE**: Uses `asyncio.run()` inside async function (anti-pattern)
- ✅ `cleanup_temp_file()` - Cleanup utility

---

## 🔴 Missing Integration Points

### **Point 1: Reprint from Archive**
**Location:** [backend/app/services/background_dispatch.py:550-680](backend/app/services/background_dispatch.py#L550-L680) - `_run_reprint_archive()`

**Current Flow:**
```
Get archive → Prepare filename → Delete from printer → Upload file → Start print
```

**Missing Step:**
- ❌ Check if `printer.plate_automation_enabled` is True
- ❌ If enabled AND automation exists for printer → Create modified temp file
- ❌ Upload modified temp file instead of original
- ❌ Clean up temp file after upload completes
- ❌ Track modified state for logging/user feedback

### **Point 2: Print from File Library**
**Location:** [backend/app/services/background_dispatch.py:730-850](backend/app/services/background_dispatch.py#L730-L850) - `_run_print_library_file()`

**Current Flow:**
```
Get library file → Create archive → Prepare filename → Delete from printer → Upload file → Start print
```

**Missing Step:**
- ❌ After archive creation, check if `printer.plate_automation_enabled` is True
- ❌ If enabled AND automation exists → Create modified temp file from archive
- ❌ Upload modified temp file (not original)
- ❌ Clean up temp file after upload completes

---

## 🎯 Proposed Solution Architecture

### **Separation of Concerns**

The solution maintains clean architecture by:

1. **Service Layer (`automation.py`)**
   - Pure logic for GCode modification and temp file creation
   - No dependencies on HTTP/dispatch logic
   - Async-compatible (fix the `asyncio.run()` issue)

2. **Dispatch Service (`background_dispatch.py`)**
   - Orchestrates when to apply automation
   - Manages temp file lifecycle (creation → upload → cleanup)
   - Handles logging and error propagation

3. **API/Routes** (no changes)
   - Automation CRUD remains unchanged
   - Printer update endpoint already supports `plate_automation_enabled`

---

## 📐 Code Completion Plan

### **Phase 1: Fix Automation Service** 
**File:** `backend/app/services/automation.py`

#### Issue 1: Remove `asyncio.run()` Anti-pattern
```python
# CURRENT (INCORRECT):
def create_temp_gcode_with_automation(original_path: Path, printer_id: int, ...):
    automation = asyncio.run(get_automation_by_printer_id(printer_id))  # ❌ Bad

# PROPOSED (CORRECT):
# Make function async, caller awaits
async def create_temp_gcode_with_automation_async(original_path: Path, printer_id: int, ...)
```

#### Addition: Helper to Check if Modification is Needed
```python
async def needs_gcode_modification(printer_id: int) -> bool:
    """Check if a printer has automation configured and enabled."""
    automation = await get_automation_by_printer_id(printer_id)
    return automation is not None and (
        bool(automation.start_code) or bool(automation.end_code)
    )
```

#### Addition: Unified Interface for Both File Types
```python
async def maybe_create_modified_file(
    file_path: Path,
    printer_id: int,
    automation_enabled: bool,
) -> Path:
    """
    If automation is enabled and configured, returns path to temp modified file.
    Otherwise returns the original file_path.
    Caller MUST cleanup returned file if it differs from original!
    """
```

---

### **Phase 2: Update Dispatch Service** 
**File:** `backend/app/services/background_dispatch.py`

#### Location A: `_run_reprint_archive()` (~line 560-640)

**New Logic:**
```python
# After: file_path = settings.base_dir / archive.file_path
# Add check:

modified_file_path = file_path
try:
    if printer.plate_automation_enabled:
        modified_file_path = await self._maybe_apply_automation(
            file_path=file_path,
            printer_id=job.printer_id,
        )
        if modified_file_path != file_path:
            await self._set_active_message(
                job, 
                f"Applying automation to {archive_filename}..."
            )
except Exception as e:
    logger.warning(
        "Failed to apply automation for archive %s on printer %s: %s",
        job.source_id, job.printer_id, e
    )
    # Continue with original file (graceful degradation)

# Later: Replace file_path with modified_file_path for upload
# Important: Track which path to cleanup later
```

#### Helper Method: `_maybe_apply_automation()`
```python
async def _maybe_apply_automation(
    self, 
    file_path: Path, 
    printer_id: int,
) -> Path:
    """
    Check if automation should apply, create temp modified file if needed.
    
    Returns:
        - temp file path if modifications applied
        - original file_path if no modifications needed
        
    Raises:
        RuntimeError on automation errors
    """
    from backend.app.services.automation import (
        create_temp_gcode_with_automation_async,
        needs_gcode_modification,
    )
    
    if not await needs_gcode_modification(printer_id):
        return file_path
    
    # Create modified temp file
    temp_path, _, _ = await create_temp_gcode_with_automation_async(
        file_path,
        printer_id,
    )
    return temp_path
```

#### Cleanup Integration
```python
# At end of _run_reprint_archive(), in finally block:
try:
    # ... upload and print logic ...
finally:
    # Cleanup modified temp file if different from original
    if modified_file_path != file_path:
        from backend.app.services.automation import cleanup_temp_file
        cleanup_temp_file(modified_file_path)
```

---

#### Location B: `_run_print_library_file()` (~line 730-820)

**New Logic:**
```python
# After: archive = await archive_service.archive_print(...)
# Add:

modified_file_path = file_path  # THIS IS LIBRARY FILE PATH
try:
    if printer.plate_automation_enabled:
        modified_file_path = await self._maybe_apply_automation(
            file_path=file_path,
            printer_id=job.printer_id,
        )
        if modified_file_path != file_path:
            await self._set_active_message(
                job,
                f"Applying automation to {library_filename}..."
            )
except Exception as e:
    logger.warning(
        "Failed to apply automation for library file %s on printer %s: %s",
        job.source_id, job.printer_id, e
    )
    # Continue with original file

# Continue with upload using modified_file_path
# Cleanup in finally block (same pattern as reprint_archive)
```

---

### **Phase 3: Error Handling & Edge Cases**

| Scenario | Current Behavior | Proposed Behavior |
|----------|---|---|
| Automation config missing | N/A | Skip modification, continue with original file |
| GCode already contains detection marker | N/A | Skip injection (handled by existing logic) |
| Temp file creation fails | N/A | Log warning, upload original file |
| Printer has automation_enabled=False | N/A | Skip modification entirely |
| File is invalid/unreadable | N/A | Log error, upload original file (graceful degrades) |

---

### **Phase 4: Logging & Observability**

Add logging at key points:
```python
logger.info(
    "Archive reprint with automation: archive_id=%s, printer=%s, "
    "automation_enabled=%s, modified=%s",
    job.source_id, printer.name, printer.plate_automation_enabled,
    modified_file_path != file_path
)

logger.debug(
    "Cleanup temp automation file for printer=%s: %s",
    printer.name, modified_file_path
)
```

---

## 🔧 Implementation Checklist

### Automation Service (`backend/app/services/automation.py`)
- [ ] Refactor `get_automation_by_printer_id()` signature if needed
- [ ] Make `create_temp_gcode_with_automation()` properly async
- [ ] Add `needs_gcode_modification(printer_id)` helper
- [ ] Add `maybe_create_modified_file()` unified interface
- [ ] Add comprehensive type hints
- [ ] Add docstrings with examples

### Background Dispatch (`backend/app/services/background_dispatch.py`)
- [ ] Add `_maybe_apply_automation()` helper method
- [ ] Update `_run_reprint_archive()`:
  - [ ] Add automation check before upload
  - [ ] Pass modified_file_path to upload
  - [ ] Add cleanup in finally block
- [ ] Update `_run_print_library_file()`:
  - [ ] Add automation check before upload
  - [ ] Pass modified_file_path to upload
  - [ ] Add cleanup in finally block
- [ ] Add comprehensive logging
- [ ] Add error handling (graceful degradation)

### Testing (Future)
- [ ] Unit tests for automation service
- [ ] Integration tests for reprint with automation
- [ ] Integration tests for library print with automation
- [ ] Edge case tests (missing config, invalid file, etc.)

---

## 🎯 Key Design Decisions

1. **Graceful Degradation**: If automation fails, continue with original file instead of blocking
2. **Lazy Evaluation**: Check `plate_automation_enabled` flag before attempting modification
3. **Temp File Lifecycle**: Dispatch service owns creation and cleanup, not service layer
4. **No Circular Dependencies**: 
   - `automation.py` knows nothing about dispatch/printing
   - `background_dispatch.py` imports from `automation.py` only
   - Clean one-way dependency
5. **Async-First**: All async operations respect event loop (no `asyncio.run()`)

---

## 📊 File Paths Summary

| File | Current | Status | Changes |
|------|---------|--------|---------|
| `automation.py` | 150 lines | ⚠️ Partial | Fix async, add helpers |
| `background_dispatch.py` | 880 lines | ⚠️ Incomplete | Add integration points |
| `automation.py` (API routes) | 106 lines | ✅ Complete | None needed |
| `printer.py` | ✅ Has flag | ✅ Complete | None needed |
| `automation.py` (model) | ✅ Complete | ✅ Complete | None needed |
| `automation.py` (schema) | ✅ Complete | ✅ Complete | None needed |

---

## 🚀 Integration Entry Points

### For Reprint Path:
1. User clicks "Reprint" on archive
2. API: `/api/v1/archives/{archive_id}/reprint` → `reprint_archive()` route
3. Route dispatches via: `background_dispatch.dispatch_reprint_archive()`
4. Dispatch enqueues job: `PrintDispatchJob(kind="reprint_archive", ...)`
5. **[NEW]** `_run_reprint_archive()` calls `_maybe_apply_automation()`
6. Original or modified file uploaded to printer
7. Print starts with modified GCode if automation applied

### For Library Print Path:
1. User clicks "Print" or "Add to Queue" on library file
2. API: `/api/v1/library/files/{file_id}/print` → `print_library_file()` route
3. Route dispatches via: `background_dispatch.dispatch_print_library_file()`
4. Dispatch enqueues job: `PrintDispatchJob(kind="print_library_file", ...)`
5. **[NEW]** `_run_print_library_file()` calls `_maybe_apply_automation()`
6. Original or modified file uploaded to printer
7. Print starts with modified GCode if automation applied

---

## ⚡ Performance Considerations

- **Temp File Creation**: O(file_size) - only when automation enabled AND configured
- **Modification Detection**: O(file_lines) - linear scan for detection markers (acceptable for GCode)
- **Memory**: Streams operations for large files using zipfile module
- **Network**: No additional round-trips (temp file stays local)

---

## 🔐 Security Considerations

- Temp files created in system tmpdir with `.3mf` or `.gcode` suffix
- Cleanup ensures no leftover files (catch all exceptions in cleanup)
- Only applied if `plate_automation_enabled=True` (per-printer opt-in)
- Automation config requires `PRINTERS_UPDATE` permission
- No user-provided GCode injection (admin-configured only)

