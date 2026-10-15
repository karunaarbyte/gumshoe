export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

/** Codes the UI treats specially; any other code is shown as a toast with its message. */
export const NETWORK = 'network';

export function isApiError(value: unknown, code?: string): value is ApiError {
  return value instanceof ApiError && (code === undefined || value.code === code);
}

export async function errorFrom(response: Response): Promise<ApiError> {
  let code = 'http_error';
  let message = `the server answered ${response.status}`;
  try {
    const body: unknown = await response.json();
    if (typeof body === 'object' && body !== null) {
      const { code: c, message: m } = body as Record<string, unknown>;
      if (typeof c === 'string') code = c;
      if (typeof m === 'string') message = m;
    }
  } catch {
    // a body that is not JSON (a proxy's error page): keep the generic code
  }
  return new ApiError(response.status, code, message);
}
