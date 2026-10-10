import { beforeEach, describe, expect, it, vi } from 'vitest';
import { analysisApi } from '../analysis';

const post = vi.hoisted(() => vi.fn());

vi.mock('../index', () => ({
  default: {
    get: vi.fn(),
    post,
  },
}));

describe('analysisApi.triggerMarketReview', () => {
  beforeEach(() => {
    post.mockReset();
    post.mockResolvedValue({
      status: 202,
      data: {
        status: 'accepted',
        message: 'accepted',
        send_notification: true,
        region: 'cn,us',
        task_id: 'market-task-1',
      },
    });
  });

  it('serializes selected markets to a comma-separated request string', async () => {
    const result = await analysisApi.triggerMarketReview({
      sendNotification: false,
      regions: ['cn', 'us'],
    });

    expect(post).toHaveBeenCalledWith(
      '/api/v1/analysis/market-review',
      {
        send_notification: false,
        report_language: undefined,
        region: 'cn,us',
      },
      expect.any(Object),
    );
    expect(result.region).toBe('cn,us');
  });

  it('omits region when the caller inherits the server default', async () => {
    await analysisApi.triggerMarketReview({ sendNotification: true });

    expect(post).toHaveBeenCalledWith(
      '/api/v1/analysis/market-review',
      {
        send_notification: true,
        report_language: undefined,
      },
      expect.any(Object),
    );
  });
});


describe('analysisApi.cancelTask', () => {
  beforeEach(() => {
    post.mockReset();
    post.mockResolvedValue({
      status: 200,
      data: {
        task_id: 'task-cancel-1',
        status: 'cancel_requested',
        progress: 64,
      },
    });
  });

  it('posts to the idempotent task-cancel endpoint', async () => {
    const result = await analysisApi.cancelTask('task/cancel 1');

    expect(post).toHaveBeenCalledWith(
      '/api/v1/analysis/tasks/task%2Fcancel%201/cancel',
    );
    expect(result.taskId).toBe('task-cancel-1');
    expect(result.status).toBe('cancel_requested');
  });
});
