import { useEffect, useRef, useState } from "react";
import { api, ApiError, readSaved, save } from "./api";
import type { Campaign, Item, Publication, Stream } from "./types";
import CreateCampaign from "./CreateCampaign";
import StreamCard from "./StreamCard";

type PushIntent = { id: string; stream: number; revision: number };
export default function App() {
  const [page, setPage] = useState<"editor" | "create">("editor");
  const [items, setItems] = useState<Item[]>([]);
  const [search, setSearch] = useState("test_bochkarev_");
  const [selected, setSelected] = useState<Item | null>(null);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const guard = useRef(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [publication, setPublication] = useState<Publication | null>(null);
  const [operation, setOperation] = useState<string | null>(null);
  const [listError, setListError] = useState("");
  const loadList = () => {
    setListError("");
    return api<Item[]>("/campaigns")
      .then(setItems)
      .catch((e) => setListError(e.message));
  };
  useEffect(() => {
    void loadList();
  }, []);
  useEffect(() => {
    setCampaign(null);
    setError("");
    setNotice("");
    setPublication(null);
    if (!selected) return;
    const controller = new AbortController();
    setLoading(true);
    const stored = readSaved<PushIntent>(`adrobot.push.${selected.id}`);
    setOperation(stored?.id || null);
    api<Campaign>(`/campaigns/${selected.id}/streams`, {
      signal: controller.signal,
    })
      .then((data) => {
        setCampaign(data);
        if (data.publication_id) setOperation(data.publication_id);
      })
      .catch((e) => {
        if (
          e.name !== "AbortError" &&
          !(e instanceof ApiError && e.status === 404)
        )
          setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [selected?.id]);
  async function refresh() {
    if (!selected) return;
    const data = await api<Campaign>(`/campaigns/${selected.id}/streams`);
    setCampaign(data);
    if (data.publication_id) setOperation(data.publication_id);
  }
  async function run(work: () => Promise<void>) {
    if (guard.current) return;
    guard.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await work();
    } catch (e) {
      setError((e as Error).message);
      if (e instanceof ApiError && e.operationId) setOperation(e.operationId);
      try {
        if (selected) await refresh();
      } catch {
        /* Keep the original actionable error. */
      }
    } finally {
      guard.current = false;
      setBusy(false);
    }
  }
  async function action(
    stream: Stream,
    kind: string,
    offerId?: number,
    share?: number,
  ) {
    await run(async () => {
      const base = `/streams/${stream.keitaro_id}`;
      const body = { expected_revision: stream.revision };
      if (kind === "push") {
        const storageKey = `adrobot.push.${selected!.id}`;
        const previous = readSaved<PushIntent>(storageKey);
        const intent =
          previous?.stream === stream.keitaro_id &&
          previous.revision === stream.revision
            ? previous
            : {
                id: crypto.randomUUID(),
                stream: stream.keitaro_id,
                revision: stream.revision,
              };
        save(storageKey, intent);
        setOperation(intent.id);
        setPublication(null);
        const result = await api<Publication>(`${base}/push`, {
          method: "POST",
          body,
          key: intent.id,
        });
        setPublication(result);
        setNotice("Изменения опубликованы в Keitaro.");
        if (result.status === "succeeded") localStorage.removeItem(storageKey);
      } else {
        const path =
          kind === "cancel"
            ? `${base}/cancel`
            : kind === "add"
              ? `${base}/offers`
              : `${base}/offers/${offerId}/${kind}`;
        await api<Stream>(path, {
          method: "POST",
          body: {
            ...body,
            ...(kind === "add" ? { offer_id: offerId } : {}),
            ...(share !== undefined ? { share } : {}),
          },
        });
        setNotice(
          kind === "cancel"
            ? "Изменения отменены."
            : "Черновик сохранён. Опубликуйте его, чтобы обновить Keitaro.",
        );
      }
      await refresh();
    });
  }
  const dirtyCount = campaign?.streams.filter((x) => x.is_dirty).length || 0;
  const filtered = items.filter((x) =>
    `${x.name} ${x.id}`.toLowerCase().includes(search.toLowerCase()),
  );
  const disabled = busy || loading || !!campaign?.sync_locked;
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#" onClick={(e) => e.preventDefault()}>
          <span className="brand-mark">
            a<span>↗</span>
          </span>
          adrobot<span className="brand-dot">.</span>
        </a>
        <span className="workspace-label">РАБОЧЕЕ ПРОСТРАНСТВО</span>
        <nav>
          <button
            disabled={busy}
            className={page === "editor" ? "nav-active" : ""}
            onClick={() => setPage("editor")}
          >
            <span>▦</span> Кампании
          </button>
          <button
            disabled={busy}
            className={page === "create" ? "nav-active" : ""}
            onClick={() => setPage("create")}
          >
            <span>＋</span> Создать кампанию
          </button>
        </nav>
        <div className="sidebar-bottom">
          <span className="avatar">AB</span>
          <div>
            <strong>Bochkarev</strong>
            <small>Тестовое пространство</small>
          </div>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <span>
            Рабочее пространство <span className="slash">/</span>{" "}
            {page === "editor" ? "Кампании" : "Создание"}
          </span>
          <span className="connection">
            <i /> Keitaro Admin
          </span>
        </header>
        <div className="content">
          <div className="page-heading">
            <div>
              <div className="section-label">УПРАВЛЕНИЕ ТРАФИКОМ</div>
              <h1>{page === "editor" ? "Кампании" : "Создать кампанию"}</h1>
              <p className="muted">
                {page === "editor"
                  ? "Настраивайте офферы. Управляйте долями. Публикуйте, когда готовы."
                  : "Соберите новую кампанию с геофильтром и оффером."}
              </p>
            </div>
            {page === "editor" && (
              <button
                className="primary"
                disabled={busy}
                onClick={() => setPage("create")}
              >
                ＋ Новая кампания
              </button>
            )}
          </div>
          {page === "create" ? (
            <CreateCampaign
              onOpen={(item) => {
                setItems((old) =>
                  old.some((x) => x.id === item.id) ? old : [item, ...old],
                );
                setSelected(item);
                setPage("editor");
              }}
            />
          ) : (
            <div className="editor-layout">
              <aside className="campaign-list panel">
                <div className="list-heading">
                  <strong>Все кампании</strong>
                  <button
                    className="icon-button"
                    aria-label="Обновить список кампаний"
                    disabled={busy}
                    onClick={() => void loadList()}
                  >
                    ↻
                  </button>
                </div>
                <label className="search-label">
                  <span className="sr-only">Поиск кампаний</span>
                  <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Поиск по названию или ID"
                  />
                </label>
                {listError && (
                  <div role="alert" className="notice error">
                    {listError}
                  </div>
                )}
                <small className="list-count">Найдено: {filtered.length}</small>
                <div className="campaign-items">
                  {filtered.map((x) => (
                    <button
                      disabled={busy || loading}
                      key={x.id}
                      className={`campaign-item ${selected?.id === x.id ? "selected" : ""}`}
                      onClick={() => setSelected(x)}
                    >
                      <span className="campaign-symbol">↗</span>
                      <span>
                        <strong>{x.name}</strong>
                        <small>#{x.id}</small>
                      </span>
                    </button>
                  ))}
                  {!filtered.length && !listError && (
                    <div className="empty-inline">
                      Кампании не найдены. Измените поиск или создайте новую.
                    </div>
                  )}
                </div>
              </aside>
              <div className="editor-main">
                {!selected ? (
                  <div className="empty-state panel">
                    <div className="empty-symbol">↗</div>
                    <h2>Выберите кампанию</h2>
                    <p>
                      Откройте кампанию слева, чтобы загрузить потоки
                      <br />и настроить распределение трафика.
                    </p>
                    <button onClick={() => setPage("create")}>
                      Создать первую кампанию →
                    </button>
                  </div>
                ) : (
                  <>
                    <div className="campaign-heading">
                      <div>
                        <small>КАМПАНИЯ #{selected.id}</small>
                        <h2>{selected.name}</h2>
                      </div>
                      <div className="actions">
                        <button
                          disabled={busy || loading}
                          onClick={() => void run(refresh)}
                        >
                          Обновить локально
                        </button>
                        <button
                          disabled={disabled || dirtyCount > 0}
                          onClick={() =>
                            void run(async () => {
                              const data = await api<Campaign>(
                                `/campaigns/${selected.id}/fetch`,
                                { method: "POST" },
                              );
                              setCampaign(data);
                              setNotice("Потоки загружены из Keitaro.");
                            })
                          }
                        >
                          ↻ Fetch из Keitaro
                        </button>
                      </div>
                    </div>
                    {error && (
                      <div role="alert" className="notice error">
                        {error}
                      </div>
                    )}
                    {notice && (
                      <div role="status" className="notice success">
                        {notice}
                      </div>
                    )}
                    {campaign?.sync_locked && (
                      <div className="notice warning">
                        <strong>Публикация требует проверки</strong>
                        <p>
                          Редактирование временно заблокировано. Проверьте
                          операцию и выполните сверку результата.
                        </p>
                      </div>
                    )}
                    {operation && (
                      <details
                        className="operation panel"
                        open={!!campaign?.sync_locked}
                      >
                        <summary>
                          Последняя публикация{" "}
                          {publication ? `· ${publication.status}` : ""}
                        </summary>
                        <code>{operation}</code>
                        {publication && (
                          <p>
                            Статус: {publication.status} · этап:{" "}
                            {publication.phase}
                            {publication.error_code
                              ? ` · ${publication.error_code}`
                              : ""}
                          </p>
                        )}
                        <div className="actions">
                          <button
                            disabled={busy}
                            onClick={() =>
                              void run(async () => {
                                setPublication(
                                  await api<Publication>(
                                    `/publications/${operation}`,
                                  ),
                                );
                                await refresh();
                              })
                            }
                          >
                            Проверить статус
                          </button>
                          <button
                            disabled={busy}
                            onClick={() =>
                              void run(async () => {
                                const data = await api<Publication>(
                                  `/publications/${operation}/reconcile`,
                                  { method: "POST" },
                                );
                                setPublication(data);
                                if (data.status === "succeeded") {
                                  localStorage.removeItem(
                                    `adrobot.push.${selected.id}`,
                                  );
                                  setNotice("Публикация подтверждена.");
                                }
                                await refresh();
                              })
                            }
                          >
                            Сверить с Keitaro
                          </button>
                          {publication &&
                            ["failed", "conflict", "succeeded"].includes(
                              publication.status,
                            ) &&
                            !campaign?.sync_locked && (
                              <button
                                disabled={busy}
                                onClick={() => {
                                  localStorage.removeItem(
                                    `adrobot.push.${selected.id}`,
                                  );
                                  setOperation(null);
                                  setPublication(null);
                                }}
                              >
                                Закрыть операцию
                              </button>
                            )}
                        </div>
                      </details>
                    )}
                    {loading ? (
                      <div role="status" className="empty-state panel">
                        Загрузка локальных данных…
                      </div>
                    ) : !campaign?.streams.length ? (
                      <div className="empty-state panel">
                        <div className="empty-symbol">⇄</div>
                        <h2>Загрузите потоки</h2>
                        <p>
                          Нажмите «Fetch из Keitaro», чтобы начать работу.
                          <br />
                          Это действие не меняет настройки в Keitaro.
                        </p>
                      </div>
                    ) : (
                      <>
                        <div className="stats">
                          <div>
                            <small>Потоки</small>
                            <strong>
                              {campaign.streams.length
                                .toString()
                                .padStart(2, "0")}
                            </strong>
                          </div>
                          <div>
                            <small>Активные офферы</small>
                            <strong>
                              {campaign.streams
                                .reduce(
                                  (n, x) =>
                                    n +
                                    x.offers.filter((o) => !o.removed).length,
                                  0,
                                )
                                .toString()
                                .padStart(2, "0")}
                            </strong>
                          </div>
                          <div>
                            <small>С изменениями</small>
                            <strong className={dirtyCount ? "amber-text" : ""}>
                              {String(dirtyCount).padStart(2, "0")}
                            </strong>
                          </div>
                        </div>
                        <div className="section-caption">
                          <span>ПОТОКИ КАМПАНИИ</span>
                          <span>Изменения сохраняются как черновик</span>
                        </div>
                        {campaign.streams.map((stream) => (
                          <StreamCard
                            key={stream.keitaro_id}
                            stream={stream}
                            disabled={disabled}
                            onAction={(...args) => void action(...args)}
                          />
                        ))}
                      </>
                    )}
                  </>
                )}
              </div>
            </div>
          )}
          <footer className="page-footer">
            Adrobot <span>Управление кампаниями Keitaro</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
