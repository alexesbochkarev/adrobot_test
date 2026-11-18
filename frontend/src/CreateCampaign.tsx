import { useEffect, useState } from "react";
import { api, readSaved, save } from "./api";
import type { CreateBody, Created, Creation, Item } from "./types";
import OfferPicker from "./OfferPicker";

type Intent = { key: string; body: CreateBody };
const storageKey = "adrobot.creation";
export default function CreateCampaign({
  onOpen,
}: {
  onOpen: (item: Item) => void;
}) {
  const [intent, setIntent] = useState<Intent | null>(() =>
    readSaved(storageKey),
  );
  const [name, setName] = useState("test_bochkarev_campaign1");
  const [country, setCountry] = useState("AU");
  const [offer, setOffer] = useState<Item | null>(null);
  const [refs, setRefs] = useState<Item[][]>([[], [], []]);
  const [ids, setIds] = useState(["", "", ""]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState<Creation | null>(null);
  const [result, setResult] = useState<Created | null>(null);
  useEffect(() => {
    const c = new AbortController();
    Promise.all(
      ["domains", "groups", "traffic-sources"].map((x) =>
        api<Item[]>(`/reference/${x}`, { signal: c.signal }),
      ),
    )
      .then(setRefs)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => c.abort();
  }, []);
  async function submit() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const body: CreateBody = intent?.body || {
        name: name.trim(),
        country_code: country.toUpperCase(),
        offer_id: offer!.id,
        ...(ids[0] ? { domain_id: Number(ids[0]) } : {}),
        ...(ids[1] ? { group_id: Number(ids[1]) } : {}),
        ...(ids[2] ? { traffic_source_id: Number(ids[2]) } : {}),
      };
      const current = intent || { key: crypto.randomUUID(), body };
      save(storageKey, current);
      setIntent(current);
      setResult(
        await api<Created>("/campaigns", {
          method: "POST",
          body: current.body,
          key: current.key,
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function check() {
    if (!intent) return;
    setBusy(true);
    setError("");
    try {
      const data = await api<Creation>(`/campaign-creations/${intent.key}`);
      setStatus(data);
      setResult(data.result);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function reset() {
    if (
      !result &&
      !window.confirm(
        "Убедитесь, что предыдущая кампания не создана. Новый ключ может создать дубль. Начать новую операцию?",
      )
    )
      return;
    localStorage.removeItem(storageKey);
    setIntent(null);
    setResult(null);
    setStatus(null);
    setError("");
  }
  return (
    <section className="create-layout">
      <div className="panel create-form">
        <div className="section-label">НОВАЯ КАМПАНИЯ</div>
        <h2>Настройте маршрут трафика</h2>
        <p className="muted">
          Два потока, один запуск. Параметры можно проверить перед созданием.
        </p>
        {error && (
          <div role="alert" className="notice error">
            {error}
          </div>
        )}
        {result ? (
          <div className="notice success">
            <h3>Кампания создана</h3>
            <p>
              {result.name} · #{result.keitaro_id}
            </p>
            <label>
              Ссылка кампании
              <input readOnly value={result.tracking_url} />
            </label>
            <button
              className="primary"
              onClick={() =>
                onOpen({ id: result.keitaro_id, name: result.name })
              }
            >
              Открыть редактор →
            </button>
            <button onClick={reset}>Создать ещё</button>
          </div>
        ) : intent ? (
          <div className="notice">
            <h3>Операция создания</h3>
            <p>{intent.body.name}</p>
            <code>{intent.key}</code>
            <p>
              {status
                ? `Статус: ${status.status} · этап: ${status.phase}`
                : "Ключ сохранён. При потере связи сначала проверьте результат."}
            </p>
            {status?.remote_campaign_id && (
              <p>Кампания в Keitaro: #{status.remote_campaign_id}</p>
            )}
            <div className="actions">
              <button disabled={busy} className="primary" onClick={check}>
                Проверить результат
              </button>
              <button disabled={busy} onClick={submit}>
                Повторить с тем же ключом
              </button>
              <button disabled={busy} onClick={reset}>
                Новая операция
              </button>
            </div>
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <fieldset disabled={busy}>
              <label>
                Название кампании
                <input
                  required
                  maxLength={255}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  pattern="test_bochkarev_.+"
                  title="Название должно начинаться с test_bochkarev_"
                />
              </label>
              <label>
                Код страны
                <input
                  required
                  pattern="[A-Za-z]{2}"
                  maxLength={2}
                  value={country}
                  onChange={(e) => setCountry(e.target.value.toUpperCase())}
                  placeholder="AU"
                />
                <small>
                  Двухбуквенный код, например AU. Посетители этой страны попадут
                  на Google.
                </small>
              </label>
              <OfferPicker value={offer} onChange={setOffer} disabled={busy} />
              <details>
                <summary>Домен, группа и источник</summary>
                <div className="advanced">
                  {["Домен", "Группа", "Источник"].map((label, index) => (
                    <label key={label}>
                      {label}
                      <select
                        value={ids[index]}
                        onChange={(e) =>
                          setIds(
                            ids.map((x, i) =>
                              i === index ? e.target.value : x,
                            ),
                          )
                        }
                      >
                        <option value="">Из настроек сервера</option>
                        {refs[index].map((x) => (
                          <option key={x.id} value={x.id}>
                            {x.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  ))}
                </div>
              </details>
              <button
                type="submit"
                className="primary wide"
                disabled={!offer || !name.trim() || busy}
              >
                {busy ? "Создаём…" : "Создать кампанию"}
              </button>
            </fieldset>
          </form>
        )}
      </div>
      <aside className="route-preview">
        <div className="section-label">КАК ПОЙДЁТ ТРАФИК</div>
        <div className="route-node">
          <span className="node-icon">↗</span>
          <strong>Ссылка кампании</strong>
          <small>Входящий трафик</small>
        </div>
        <div className="route-line" />
        <div className="route-node">
          <span className="badge">01 · GEO</span>
          <strong>Страна: {intent?.body.country_code || country || "—"}</strong>
          <small>Совпадение → Google</small>
        </div>
        <div className="route-line" />
        <div className="route-node accented">
          <span className="badge">02 · ОФФЕР</span>
          <strong>Остальные посетители</strong>
          <small>
            {offer?.name ||
              (intent
                ? `Оффер #${intent.body.offer_id}`
                : "Выбранный оффер")}{" "}
            · 100%
          </small>
        </div>
        <p className="muted">
          Кампания включится только после создания обоих потоков.
        </p>
      </aside>
    </section>
  );
}
