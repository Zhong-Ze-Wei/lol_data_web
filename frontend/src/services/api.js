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

export async function streamAIQuery({ body, signal, onResult }) {
  const response = await fetch("/api/ai/query-stream", {
    method: "POST",
    signal,
    headers: {
      Accept: "application/x-ndjson",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
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
    const error = data.error;
    throw new ApiError(
      typeof error === "string"
        ? error
        : error?.message || data.message || `请求失败（${response.status}）`,
      response.status,
      error?.code || data.code,
    );
  }
  const invalid = () =>
    new ApiError(
      "分析响应不完整，请重新发送问题。",
      response.status,
      "incomplete_response",
    );
  if (!response.body) throw invalid();
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let buffer = "";
  let result;
  let completed = false;

  function decode(value, stream = false) {
    try {
      return decoder.decode(value, { stream });
    } catch {
      throw invalid();
    }
  }

  function consume(line) {
    if (!line.trim()) return;
    let event;
    try {
      event = JSON.parse(line);
    } catch {
      throw invalid();
    }
    if (!event || completed) throw invalid();
    if (event.type === "error")
      throw new ApiError(event.error, response.status, event.code);
    if (event.type === "done") {
      if (!result || result.explanation_status === "pending") throw invalid();
      completed = true;
      return;
    }
    if (
      !event.result ||
      typeof event.result !== "object" ||
      Array.isArray(event.result)
    )
      throw invalid();
    if (event.type === "data") {
      if (
        result ||
        !["pending", "complete", "unavailable", "skipped"].includes(
          event.result.explanation_status,
        )
      )
        throw invalid();
    } else if (event.type === "explanation") {
      if (
        result?.explanation_status !== "pending" ||
        !["complete", "unavailable"].includes(event.result.explanation_status)
      )
        throw invalid();
    } else throw invalid();
    result = event.result;
    onResult(result, event.type);
  }

  try {
    if (
      response.headers.get("Content-Type")?.split(";")[0] !==
      "application/x-ndjson"
    )
      throw invalid();
    while (!completed) {
      const chunk = await reader.read();
      if (chunk.done) {
        buffer += decode();
        if (buffer.trim()) consume(buffer);
        break;
      }
      buffer += decode(chunk.value, true);
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) consume(line);
    }
    if (!completed) throw invalid();
    return result;
  } finally {
    try {
      await reader.cancel();
    } catch {
      // 断开的响应取消也会拒绝；保留原来的解析或网络错误。
    }
    reader.releaseLock();
  }
}
