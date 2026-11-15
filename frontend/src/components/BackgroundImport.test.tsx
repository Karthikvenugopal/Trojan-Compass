import { expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BackgroundImport } from './BackgroundImport';

it('uses uploads directly without displaying extracted text or a review step', async () => {
  const user = userEvent.setup(); const use = vi.fn();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ text: 'Synthetic theatre experience.' }), { status: 200 })));
  render(<BackgroundImport disabled={false} onUse={use} />);
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /Add a resume/ }));
  await user.upload(screen.getByLabelText('Upload background document'), new File(['synthetic'], 'resume.pdf', { type: 'application/pdf' }));
  await waitFor(() => expect(use).toHaveBeenCalledWith('Use my resume as background.\nSynthetic theatre experience.'));
  expect(screen.queryByText('Synthetic theatre experience.')).not.toBeInTheDocument();
  expect(screen.queryByText(/Review the text/)).not.toBeInTheDocument();
});

it('uses a LinkedIn URL via POST and explains blocked access without adding fake background', async () => {
  const user = userEvent.setup(); const use = vi.fn();
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { message: 'LinkedIn blocked access. Upload a profile PDF or paste text instead.' } }), { status: 422 }));
  vi.stubGlobal('fetch', fetch);
  render(<BackgroundImport disabled={false} onUse={use} />);
  await user.click(screen.getByRole('button', { name: /Add a resume/ }));
  await user.click(screen.getByRole('button', { name: 'LinkedIn' }));
  await user.type(screen.getByRole('textbox', { name: 'LinkedIn profile URL' }), 'https://www.linkedin.com/in/synthetic');
  await user.click(screen.getByRole('button', { name: 'Use LinkedIn profile' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Upload a profile PDF');
  expect(use).not.toHaveBeenCalled();
  expect(fetch.mock.calls[0][0]).toMatch(/\/api\/import-linkedin$/);
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ url: 'https://www.linkedin.com/in/synthetic' });
});

it('keeps optional pasted background and clears it on close', async () => {
  const user = userEvent.setup(); const use = vi.fn();
  render(<BackgroundImport disabled={false} onUse={use} />);
  await user.click(screen.getByRole('button', { name: /Add a resume/ }));
  await user.click(screen.getByText('Paste background instead'));
  await user.type(screen.getByRole('textbox', { name: 'Background text' }), 'Synthetic volunteering');
  await user.click(screen.getByRole('button', { name: 'Use background' }));
  expect(use).toHaveBeenCalledWith('Use my resume as background.\nSynthetic volunteering');
  await user.click(screen.getByRole('button', { name: /Add a resume/ }));
  await user.click(screen.getByText('Paste background instead'));
  expect(screen.getByRole('textbox', { name: 'Background text' })).toHaveValue('');
});

it('aborts a pending import when closed and does not add a late response', async () => {
  const user = userEvent.setup(); const use = vi.fn();
  let resolve!: (response: Response) => void;
  const fetch = vi.fn().mockImplementation(() => new Promise<Response>(done => { resolve = done; }));
  vi.stubGlobal('fetch', fetch);
  render(<BackgroundImport disabled={false} onUse={use} />);
  await user.click(screen.getByRole('button', { name: /Add a resume/ }));
  await user.upload(screen.getByLabelText('Upload background document'), new File(['x'], 'resume.pdf', { type: 'application/pdf' }));
  await user.click(screen.getByRole('button', { name: 'Close and clear import' }));
  expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
  resolve(new Response(JSON.stringify({ text: 'Late private text' }), { status: 200 }));
  await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  expect(use).not.toHaveBeenCalled();
});
