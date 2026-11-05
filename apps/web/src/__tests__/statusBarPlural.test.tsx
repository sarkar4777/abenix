import { render, screen } from '@testing-library/react';

const stats = { active_executions: 0, today_executions: 1, today_failed: 0 };

vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ user: { full_name: 'A', email: 'a@b.dev' } }) }));
vi.mock('@/hooks/useApi', () => ({
  useApi: () => ({ data: stats, isLoading: false, error: null, meta: null, mutate: vi.fn() }),
}));

import StatusBar from '@/components/layout/StatusBar';

describe('status bar run count', () => {
  it('says 1 run today', () => {
    stats.today_executions = 1;
    render(<StatusBar />);
    expect(screen.getByTestId('status-today')).toHaveTextContent('1 run today');
  });
  it('says 2 runs today', () => {
    stats.today_executions = 2;
    render(<StatusBar />);
    expect(screen.getByTestId('status-today')).toHaveTextContent('2 runs today');
  });
});
