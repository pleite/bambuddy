import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { render } from '../utils';
import { server } from '../mocks/server';
import { PlateAutomationModal } from '../../components/PlateAutomationModal';

describe('PlateAutomationModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('creates automation when editing new values', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onSaved = vi.fn();
    let capturedBody: Record<string, unknown> | null = null;

    server.use(
      http.post('/api/v1/printers/:id/automation', async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          id: 101,
          printer_id: 1,
          start_code: capturedBody.start_code ?? '',
          start_code_detect: capturedBody.start_code_detect ?? '',
          start_code_after: capturedBody.start_code_after ?? '',
          end_code: capturedBody.end_code ?? '',
          end_code_detect: capturedBody.end_code_detect ?? '',
          end_code_after: capturedBody.end_code_after ?? '',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        });
      })
    );

    render(
      <PlateAutomationModal isOpen={true} onClose={onClose} printerId={1} initial={null} onSaved={onSaved} />
    );

    const textboxes = screen.getAllByRole('textbox');
    await user.type(textboxes[0], 'M1002 ; start');
    await user.type(textboxes[3], 'M400 ; end');

    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledTimes(1);
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    expect(capturedBody).not.toBeNull();
    expect(capturedBody?.start_code).toBe('M1002 ; start');
    expect(capturedBody?.end_code).toBe('M400 ; end');
  });

  it('updates automation when initial automation exists', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onSaved = vi.fn();
    let capturedBody: Record<string, unknown> | null = null;

    server.use(
      http.patch('/api/v1/automation/:id', async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          id: 7,
          printer_id: 1,
          start_code: capturedBody.start_code ?? '',
          start_code_detect: capturedBody.start_code_detect ?? '',
          start_code_after: capturedBody.start_code_after ?? '',
          end_code: capturedBody.end_code ?? '',
          end_code_detect: capturedBody.end_code_detect ?? '',
          end_code_after: capturedBody.end_code_after ?? '',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-02T00:00:00Z',
        });
      })
    );

    render(
      <PlateAutomationModal
        isOpen={true}
        onClose={onClose}
        printerId={1}
        initial={{
          id: 7,
          printer_id: 1,
          start_code: 'G28',
          start_code_detect: '',
          start_code_after: '',
          end_code: '',
          end_code_detect: '',
          end_code_after: '',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }}
        onSaved={onSaved}
      />
    );

    const textboxes = screen.getAllByRole('textbox');
    await user.clear(textboxes[0]);
    await user.type(textboxes[0], 'G29');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledTimes(1);
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    expect(capturedBody?.start_code).toBe('G29');
  });

  it('deletes automation when all fields are blank for existing row', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onSaved = vi.fn();
    let deleteCallCount = 0;

    server.use(
      http.delete('/api/v1/automation/:id', () => {
        deleteCallCount += 1;
        return new HttpResponse(null, { status: 204 });
      })
    );

    render(
      <PlateAutomationModal
        isOpen={true}
        onClose={onClose}
        printerId={1}
        initial={{
          id: 9,
          printer_id: 1,
          start_code: '',
          start_code_detect: '',
          start_code_after: '',
          end_code: '',
          end_code_detect: '',
          end_code_after: '',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }}
        onSaved={onSaved}
      />
    );

    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(deleteCallCount).toBe(1);
      expect(onSaved).toHaveBeenCalledTimes(1);
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });
});