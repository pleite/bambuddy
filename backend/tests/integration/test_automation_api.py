"""Integration tests for plate automation API endpoints."""

import pytest
from httpx import AsyncClient


class TestAutomationAPI:
    """Integration tests for /api/v1/printers/{id}/automation and /api/v1/automation/{id}."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_list_automation_returns_404_for_missing_printer(self, async_client: AsyncClient):
        """Listing automation for a missing printer should return 404."""
        response = await async_client.get("/api/v1/printers/9999/automation")

        assert response.status_code == 404
        assert response.json()["detail"] == "Printer not found"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_create_then_list_automation_for_printer(self, async_client: AsyncClient, printer_factory, db_session):
        """Create automation row and verify it appears in list endpoint."""
        printer = await printer_factory()

        payload = {
            "start_code": "M1002 ; start",
            "start_code_detect": "M1002",
            "start_code_after": "; HEADER_END",
            "end_code": "M400 ; end",
            "end_code_detect": "M400",
            "end_code_after": "; END_PRINT",
        }

        create_response = await async_client.post(f"/api/v1/printers/{printer.id}/automation", json=payload)

        assert create_response.status_code == 200
        created = create_response.json()
        assert created["printer_id"] == printer.id
        assert created["start_code"] == payload["start_code"]
        assert created["end_code"] == payload["end_code"]

        list_response = await async_client.get(f"/api/v1/printers/{printer.id}/automation")

        assert list_response.status_code == 200
        rows = list_response.json()
        assert len(rows) == 1
        assert rows[0]["id"] == created["id"]
        assert rows[0]["start_code_detect"] == "M1002"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_update_automation_row(self, async_client: AsyncClient, printer_factory, db_session):
        """Patch endpoint updates only provided fields."""
        printer = await printer_factory()

        create_response = await async_client.post(
            f"/api/v1/printers/{printer.id}/automation",
            json={
                "start_code": "G28",
                "start_code_after": ";START",
                "end_code": "M104 S0",
            },
        )
        automation_id = create_response.json()["id"]

        update_response = await async_client.patch(
            f"/api/v1/automation/{automation_id}",
            json={"start_code": "G29", "end_code_detect": "M104"},
        )

        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["id"] == automation_id
        assert updated["start_code"] == "G29"
        assert updated["end_code_detect"] == "M104"
        assert updated["start_code_after"] == ";START"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_update_missing_automation_returns_404(self, async_client: AsyncClient):
        """Updating non-existent automation row should return 404."""
        response = await async_client.patch("/api/v1/automation/9999", json={"start_code": "G28"})

        assert response.status_code == 404
        assert response.json()["detail"] == "Automation not found"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_delete_automation_row(self, async_client: AsyncClient, printer_factory, db_session):
        """Delete endpoint removes automation row and returns success payload."""
        printer = await printer_factory()

        create_response = await async_client.post(
            f"/api/v1/printers/{printer.id}/automation",
            json={"start_code": "G28"},
        )
        automation_id = create_response.json()["id"]

        delete_response = await async_client.delete(f"/api/v1/automation/{automation_id}")

        assert delete_response.status_code == 200
        assert delete_response.json() == {"success": True}

        list_response = await async_client.get(f"/api/v1/printers/{printer.id}/automation")
        assert list_response.status_code == 200
        assert list_response.json() == []