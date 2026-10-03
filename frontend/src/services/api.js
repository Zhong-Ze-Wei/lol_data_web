export class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function apiUrl(path, params = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== "" && value !== null && value !== undefined)
      query.set(key, String(value));
  }
  return `${path}${query.size ? `?${query}` : ""}`;
}

export async function request(
  path,
  { params, signal, method = "GET", body } = {},
) {
  const response = await fetch(apiUrl(path, params), {
    method,
    signal,
    headers:
      body === undefined
        ? { Accept: "application/json" }
        : { Accept: "application/json", "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(
      "服务返回了无法读取的内容，请稍后重试。",
      response.status,
      "invalid_response",
    );
  }
  if (!response.ok) {
    const error = data.error;
    throw new ApiError(
      typeof error === "string"
        ? error
        : error?.message || data.message || `请求失败（${response.status}）`,
      response.status,
      error?.code || data.code,
    );
  }
  return data;
}
