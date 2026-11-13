// 인증과 서비스 요청 접수·조회는 실제 API를 사용한다. 실패 시 가짜 성공으로 대체하지 않는다.

const API_ERRORS = {
  INVALID_CREDENTIALS: '아이디 또는 비밀번호가 올바르지 않습니다.',
  TOO_MANY_ATTEMPTS: '시도가 너무 많습니다. 10분 뒤 다시 시도하세요.',
}

export class ApiError extends Error {
  constructor(message, status, code) { super(message); this.status = status; this.code = code }
}

export async function call(path, { method = 'GET', body, csrf } = {}) {
  const headers = {}
  if (body) headers['Content-Type'] = 'application/json'
  if (csrf && method !== 'GET') headers['X-CSRF-Token'] = csrf
  let response
  try {
    response = await fetch(`/api/v1${path}`, { method, headers, credentials: 'same-origin', cache: 'no-store', body: body ? JSON.stringify(body) : undefined })
  } catch { throw new ApiError('서버에 연결하지 못했습니다.') }
  if (response.status === 204) return null
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : '요청을 처리하지 못했습니다.'
    throw new ApiError(API_ERRORS[data?.code] || detail, response.status, data?.code)
  }
  return data
}
