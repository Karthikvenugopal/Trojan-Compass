import { expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CareerGuide } from './CareerGuide';
import type { CareerGuidance } from '../types';

const source = { url: 'https://example.org/evidence', title: 'Synthetic evidence', checked_at: null };
export const plan: CareerGuidance = {
  mode: 'plan', goal: 'Synthetic career', headline: 'A working roadmap', suggested_paths: [],
  skills: [{ name: 'Mathematics', status: 'unknown', category: 'knowledge', basis: 'Synthetic occupation baseline', sources: [source], student_evidence: [] }],
  actions: [{ id: 'research', kind: 'research', title: 'Synthetic research pathway', summary: 'A pathway to review', why_relevant: 'A field connection', skill_names: ['Mathematics'], url: source.url, sources: [source], availability: 'unknown', checks: ['Check eligibility'], term: null }],
  steps: [{ id: 'learn', title: 'Confirm your starting point', description: 'Assess one skill', skill_names: ['Mathematics'], action_ids: ['research'], depends_on: [] }],
  next_question: { text: 'How comfortable are you with Mathematics?', options: [], requested_fields: ['skills.mathematics'], reason: 'Prioritize the next step' }, limitations: ['Availability unknown'],
};
it('shows unknown distinctly and sends an explicit skill assessment', async () => {
  const user = userEvent.setup(); const save = vi.fn();
  render(<CareerGuide guidance={plan} disabled={false} onEdit={save} />);
  expect(screen.getByText('Not assessed')).toBeInTheDocument();
  expect(screen.queryByText('Confirmed development need')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Not learned yet' }));
  expect(save).toHaveBeenCalledWith({ field: 'skills.mathematics', status: 'provided', value: 'I have not learned Mathematics yet.' }, 'Mathematics');
  expect(screen.getByText('Availability unknown', { selector: '.availability-note' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /View official source/ })).toHaveAttribute('href', source.url);
});
it('requires a student to choose a suggested direction', async () => {
  const user = userEvent.setup(); const save = vi.fn();
  render(<CareerGuide guidance={{ ...plan, mode: 'explore', goal: null, skills: [], actions: [], next_question: null, suggested_paths: [{ id: 'design', title: 'Graphic designer', why_consider: 'An option to explore', select_message: 'Explore design', sources: [source] }] }} disabled={false} onEdit={save} />);
  expect(save).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: /Explore this path/ }));
  expect(save).toHaveBeenCalledWith({ field: 'target', status: 'provided', value: 'Graphic designer' }, 'career target');
});
