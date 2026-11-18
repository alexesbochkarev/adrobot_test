const messages: Record<string, string> = {
  unpublished_changes:
    "Есть неопубликованные изменения. Опубликуйте или отмените их перед Fetch.",
  stale_revision:
    "Поток уже изменён. Обновите локальные данные и повторите действие.",
  remote_stream_changed:
    "Кто-то изменил поток в Keitaro. Отмените черновик и выполните Fetch.",
  cannot_remove_last_active_offer: "Нельзя удалить последний активный оффер.",
  pinned_total_exceeds_100: "Сумма закреплённых долей превышает 100%.",
  all_shares_pinned_without_100_total:
    "У закреплённых офферов сумма должна быть 100%. Снимите одно закрепление.",
  campaign_sync_locked:
    "Кампания заблокирована до проверки незавершённой публикации.",
  campaign_busy_or_changed:
    "Кампания изменилась или занята. Обновите локальные данные.",
  offer_already_active: "Этот оффер уже добавлен в поток.",
  keitaro_not_configured: "Подключение к Keitaro не настроено на сервере.",
  keitaro_access_denied:
    "Keitaro отказал в доступе. Проверьте настройки сервера.",
  keitaro_timeout:
    "Keitaro не ответил вовремя. Проверьте результат операции перед повтором.",
  publication_verification_failed:
    "Запись отправлена, но результат не подтверждён. Выполните сверку.",
  publication_not_confirmed:
    "Состояние Keitaro пока не совпадает с ожидаемым. Блокировка сохранена.",
  publication_not_reconcilable:
    "Операция требует ручной проверки. Автоматическая сверка сейчас недоступна.",
  publication_requires_review:
    "Эта публикация уже выполнялась. Проверьте её результат.",
  creation_requires_review:
    "Создание уже выполнялось. Проверьте результат, чтобы избежать дубля.",
  offer_unavailable: "Оффер недоступен или неактивен.",
  no_unpublished_changes: "Нет изменений для публикации.",
};
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    public operationId?: string,
    message?: string,
  ) {
    super(
      message ||
        messages[code] ||
        `Не удалось выполнить запрос (${status}): ${code}`,
    );
  }
}
export async function api<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    key?: string;
    signal?: AbortSignal;
  } = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch("/api/v1" + path, {
      method: options.method || "GET",
      signal: options.signal,
      headers: {
        "Content-Type": "application/json",
        ...(options.key ? { "Idempotency-Key": options.key } : {}),
      },
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new ApiError(
      0,
      "network",
      undefined,
      "Нет связи с backend. Если выполнялась запись, сначала проверьте результат операции.",
    );
  }
  let data;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(
      response.status,
      "invalid_response",
      undefined,
      "Backend вернул неожиданный ответ. Проверьте, что FastAPI запущен.",
    );
  }
  if (!response.ok) {
    const detail = data.detail;
    if (Array.isArray(detail))
      throw new ApiError(
        response.status,
        "validation",
        undefined,
        detail
          .map(
            (x: { loc: string[]; msg: string }) =>
              `${x.loc.slice(1).join(".")}: ${x.msg}`,
          )
          .join("; "),
      );
    throw new ApiError(
      response.status,
      detail?.code || String(detail || "request_failed"),
      detail?.operation_id,
    );
  }
  return data as T;
}
export function readSaved<T>(key: string): T | null {
  try {
    return JSON.parse(localStorage.getItem(key) || "null");
  } catch {
    return null;
  }
}
export function save(key: string, value: unknown) {
  // Do not submit a write when its recovery key cannot be persisted.
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    throw new Error(
      "Не удалось сохранить ключ операции в браузере. Разрешите локальное хранилище.",
    );
  }
}
